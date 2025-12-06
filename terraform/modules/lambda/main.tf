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

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = var.source_path
  output_path = "${path.module}/.builds/${var.function_name}.zip"
}

resource "aws_lambda_function" "this" {
  function_name = "${var.function_name}"
  description   = var.description
  role          = aws_iam_role.lambda.arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size

  filename         = data.archive_file.lambda.output_path
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
