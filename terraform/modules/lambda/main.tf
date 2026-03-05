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

# Build Lambda with dependencies if requirements.txt exists
resource "null_resource" "build_lambda" {
  triggers = {
    requirements   = fileexists("${var.source_path}/requirements.txt") ? filemd5("${var.source_path}/requirements.txt") : "no-requirements"
    source_hash    = sha256(join("", [for f in fileset(var.source_path, "**/*.py") : filesha256("${var.source_path}/${f}")]))
    build_platform = "manylinux2014_x86_64" # Force rebuild when platform changes
    build_version  = "7"                    # Increment to force rebuild
  }

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-Command"]
    command = <<-EOT
      $ErrorActionPreference = 'Stop'

      $BuildDir = "${path.module}/.builds/${var.function_name}"
      if (Test-Path $BuildDir) {
        Remove-Item -Recurse -Force $BuildDir
      }
      New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

      $ReqFile = "${var.source_path}/requirements.txt"
      if (Test-Path $ReqFile) {
        Write-Host "Installing Python dependencies for Linux/Lambda..."
        python -m pip install `
          -r $ReqFile `
          -t $BuildDir `
          --platform manylinux2014_x86_64 `
          --implementation cp `
          --python-version 3.12 `
          --abi cp312 `
          --only-binary=:all: `
          --upgrade `
          --quiet
      }

      Get-ChildItem -Path "${var.source_path}" -Filter "*.py" -File -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item -Force $_.FullName -Destination $BuildDir }

      $LibDir = "${var.source_path}/lib"
      if (Test-Path $LibDir) {
        $BuildLibDir = Join-Path $BuildDir "lib"
        New-Item -ItemType Directory -Force -Path $BuildLibDir | Out-Null

        Get-ChildItem -Path $LibDir -Filter "*.py" -File -ErrorAction SilentlyContinue |
          ForEach-Object { Copy-Item -Force $_.FullName -Destination $BuildLibDir }
      }
    EOT
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/.builds/${var.function_name}"
  output_path = "${path.module}/.builds/${var.function_name}.zip"

  depends_on = [null_resource.build_lambda]
}

# Upload to S3 if enabled
resource "aws_s3_object" "lambda_package" {
  count  = var.use_s3_deployment ? 1 : 0
  bucket = var.s3_bucket_name
  key    = "lambda-packages/${var.function_name}/${data.archive_file.lambda.output_base64sha256}.zip"
  source = data.archive_file.lambda.output_path
  etag   = data.archive_file.lambda.output_md5
}

resource "aws_lambda_function" "this" {
  function_name = var.function_name
  description   = var.description
  role          = aws_iam_role.lambda.arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size

  # Use S3 if enabled (for large packages), otherwise use direct upload
  s3_bucket        = var.use_s3_deployment ? var.s3_bucket_name : null
  s3_key           = var.use_s3_deployment ? aws_s3_object.lambda_package[0].key : null
  filename         = var.use_s3_deployment ? null : data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  layers = var.layers

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
