# ==============================================================================
# IAM Role for Lambda
# ==============================================================================

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

# Basic Lambda execution policy (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC access policy (if VPC is configured)
resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  count      = length(var.subnet_ids) > 0 ? 1 : 0
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Custom policy for additional permissions
data "aws_iam_policy_document" "custom" {
  count = length(var.attach_policy_statements) > 0 ? 1 : 0

  dynamic "statement" {
    for_each = var.attach_policy_statements
    content {
      effect    = statement.value.effect
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "custom" {
  count  = length(var.attach_policy_statements) > 0 ? 1 : 0
  name   = "${var.function_name}-custom-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.custom[0].json
}

# S3 access for Lambda deployment package
resource "aws_iam_role_policy" "s3_deployment" {
  count = var.use_s3_deployment ? 1 : 0
  name  = "${var.function_name}-s3-deployment-policy"
  role  = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}/lambda-packages/${var.function_name}/*"
        ]
      }
    ]
  })
}

# ==============================================================================
# Security Group for Lambda (if VPC)
# ==============================================================================

resource "aws_security_group" "lambda" {
  count       = length(var.subnet_ids) > 0 && length(var.security_group_ids) == 0 ? 1 : 0
  name        = "${var.function_name}-sg"
  description = "Security group for ${var.function_name} Lambda"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = merge(var.tags, {
    Name = "${var.function_name}-sg"
  })
}

# ==============================================================================
# Lambda Function
# ==============================================================================

locals {
  is_windows = can(regex("^[A-Za-z]:", abspath(path.root)))

  shared_package_abs  = var.shared_package_path == "" ? "" : abspath(var.shared_package_path)
  shared_path_trigger = var.shared_package_path == "" ? "no-shared" : (try(sha256(join("", [for f in fileset(local.shared_package_abs, "**/*.py") : filesha256("${local.shared_package_abs}/${f}")])), "shared-missing"))
}

# Build Lambda with dependencies if requirements.txt exists
resource "null_resource" "build_lambda_unix" {
  count = local.is_windows ? 0 : 1

  triggers = {
    requirements   = fileexists("${var.source_path}/requirements.txt") ? filemd5("${var.source_path}/requirements.txt") : "no-requirements"
    source_hash    = sha256(join("", [for f in fileset(var.source_path, "**/*.py") : filesha256("${var.source_path}/${f}")]))
    shared_hash    = local.shared_path_trigger
    build_platform = "manylinux2014_x86_64" # Force rebuild when platform changes
    build_version  = "12"                   # Increment to force rebuild
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      rm -rf "${path.module}/.builds/${var.function_name}"
      mkdir -p "${path.module}/.builds/${var.function_name}"
      if [ -f "${var.source_path}/requirements.txt" ]; then
        echo "Installing Python dependencies for Linux/Lambda..."
        if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
        "$PY" -m pip install \
          -r "${var.source_path}/requirements.txt" \
          -t "${path.module}/.builds/${var.function_name}" \
          --platform manylinux2014_x86_64 \
          --implementation cp \
          --python-version 3.12 \
          --abi cp312 \
          --only-binary=:all: \
          --upgrade \
          --quiet
      fi
      find "${var.source_path}" -maxdepth 1 -name '*.py' -exec cp {} "${path.module}/.builds/${var.function_name}/" \;
      if [ -d "${var.source_path}/lib" ]; then
        mkdir -p "${path.module}/.builds/${var.function_name}/lib"
        find "${var.source_path}/lib" -maxdepth 1 -name '*.py' -exec cp {} "${path.module}/.builds/${var.function_name}/lib/" \;
      fi
      if [ -n "${var.shared_package_path}" ]; then
        mkdir -p "${path.module}/.builds/${var.function_name}/shared"
        cp -R "${local.shared_package_abs}/." "${path.module}/.builds/${var.function_name}/shared/"
      fi
    EOT
  }
}

resource "null_resource" "build_lambda_windows" {
  count = local.is_windows ? 1 : 0

  triggers = {
    requirements   = fileexists("${var.source_path}/requirements.txt") ? filemd5("${var.source_path}/requirements.txt") : "no-requirements"
    source_hash    = sha256(join("", [for f in fileset(var.source_path, "**/*.py") : filesha256("${var.source_path}/${f}")]))
    shared_hash    = local.shared_path_trigger
    build_platform = "manylinux2014_x86_64"
    build_version  = "12"
  }

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-Command"]
    command     = <<-EOT
      $ErrorActionPreference = 'Stop'
      $buildDir = "${path.module}/.builds/${var.function_name}"
      $sourceDir = "${var.source_path}"
      if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
      New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
      $requirements = Join-Path $sourceDir "requirements.txt"
      if (Test-Path $requirements) {
        Write-Host "Installing Python dependencies for Linux/Lambda..."
        $py = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } else { "python" }
        & $py -m pip install -r $requirements -t $buildDir --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --abi cp312 --only-binary=:all: --upgrade --quiet
      }
      Get-ChildItem -Path $sourceDir -Filter *.py -File | ForEach-Object {
        Copy-Item $_.FullName -Destination $buildDir -Force
      }
      $libDir = Join-Path $sourceDir "lib"
      if (Test-Path $libDir) {
        $targetLibDir = Join-Path $buildDir "lib"
        New-Item -ItemType Directory -Force -Path $targetLibDir | Out-Null
        Get-ChildItem -Path $libDir -Filter *.py -File | ForEach-Object {
          Copy-Item $_.FullName -Destination $targetLibDir -Force
        }
      }
      if ("${var.shared_package_path}" -ne "") {
        $sp = "${local.shared_package_abs}"
        $tshared = Join-Path $buildDir "shared"
        New-Item -ItemType Directory -Force -Path $tshared | Out-Null
        Copy-Item -Path (Join-Path $sp "*") -Destination $tshared -Recurse -Force
      }
    EOT
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/.builds/${var.function_name}"
  output_path = "${path.module}/.builds/${var.function_name}.zip"

  depends_on = [null_resource.build_lambda_unix, null_resource.build_lambda_windows]
}

# Upload to S3 if enabled
resource "aws_s3_object" "lambda_package" {
  count  = var.use_s3_deployment ? 1 : 0
  bucket = var.s3_bucket_name
  # Hex SHA-256 avoids +, /, = in the key; base64 breaks Lambda UpdateFunctionCode GetObject for some keys.
  key    = "lambda-packages/${var.function_name}/${data.archive_file.lambda.output_sha256}.zip"
  source = data.archive_file.lambda.output_path
  etag   = data.archive_file.lambda.output_md5
}

resource "aws_lambda_function" "this" {
  filename      = var.use_s3_deployment ? null : data.archive_file.lambda.output_path
  function_name = var.function_name
  role          = aws_iam_role.lambda.arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size
  layers        = var.layers

  s3_bucket        = var.use_s3_deployment ? var.s3_bucket_name : null
  s3_key           = var.use_s3_deployment ? aws_s3_object.lambda_package[0].key : null
  source_code_hash = data.archive_file.lambda.output_base64sha256


  reserved_concurrent_executions = var.reserved_concurrent_executions

  ephemeral_storage {
    size = var.ephemeral_storage_size
  }

  dynamic "vpc_config" {
    for_each = length(var.subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids = var.subnet_ids
      security_group_ids = length(var.security_group_ids) > 0 ? var.security_group_ids : [
        aws_security_group.lambda[0].id
      ]
    }
  }

  environment {
    variables = var.environment_variables
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy_attachment.lambda_vpc,
  ]
}

# SQS trigger: receive/delete/get queue attributes
resource "aws_iam_role_policy_attachment" "lambda_sqs" {
  count      = var.sqs_trigger_enabled ? 1 : 0
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count            = var.sqs_trigger_enabled ? 1 : 0
  event_source_arn = var.sqs_queue_arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = var.sqs_batch_size
  enabled          = true

  dynamic "scaling_config" {
    for_each = var.sqs_maximum_concurrency != null ? [1] : []
    content {
      maximum_concurrency = var.sqs_maximum_concurrency
    }
  }

  depends_on = [aws_iam_role_policy_attachment.lambda_sqs]
}

# ==============================================================================
# S3 Trigger (optional)
# ==============================================================================

resource "aws_lambda_permission" "s3" {
  count         = var.s3_trigger_enabled ? 1 : 0
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.s3_bucket_arn
}

resource "aws_s3_bucket_notification" "lambda" {
  count  = var.s3_trigger_enabled ? 1 : 0
  bucket = var.s3_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.this.arn
    events              = var.s3_events
    filter_prefix       = var.s3_filter_prefix
    filter_suffix       = var.s3_filter_suffix
  }

  depends_on = [aws_lambda_permission.s3]
}

# ==============================================================================
# CloudWatch Log Group
# ==============================================================================

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.this.function_name}"
  retention_in_days = 14
  tags              = var.tags
}
