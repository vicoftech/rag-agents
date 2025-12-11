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

# Custom policy for Bedrock and Lambda permissions
data "aws_iam_policy_document" "lambda_policy" {
  # Bedrock permissions
  statement {
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = [
      "arn:aws:bedrock:${var.region}::foundation-model/*"
    ]
  }

  # Bedrock Agent Runtime permissions
  statement {
    effect = "Allow"
    actions = [
      "bedrock-agent-runtime:InvokeAgent"
    ]
    resources = [
      "arn:aws:bedrock-agent:${var.region}:*:agent/*"
    ]
  }

  # Invoke RAG query Lambda
  statement {
    effect = "Allow"
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = [
      "arn:aws:lambda:${var.region}:*:function:${var.lambda_query_function_name}*"
    ]
  }
}

resource "aws_iam_role_policy" "lambda_custom" {
  name   = "${var.function_name}-custom-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_policy.json
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
  function_name = var.function_name
  description   = var.description
  role          = aws_iam_role.lambda.arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  ephemeral_storage {
    size = var.ephemeral_storage_size
  }

  dynamic "vpc_config" {
    for_each = length(var.subnet_ids) > 0 ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
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
# Bedrock Agent
# ==============================================================================

resource "aws_bedrock_agent" "this" {
  agent_name                = var.agent_name
  agent_resource_role_arn   = aws_iam_role.bedrock_agent.arn
  foundation_model          = var.agent_model_id
  description               = var.agent_description
  instruction               = "You are a RAG (Retrieval Augmented Generation) agent that searches knowledge bases and generates responses based on found context."

  tags = var.tags
}

# IAM Role for Bedrock Agent
data "aws_iam_policy_document" "bedrock_agent_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "bedrock_agent" {
  name               = "${var.agent_name}-bedrock-agent-role"
  assume_role_policy = data.aws_iam_policy_document.bedrock_agent_assume.json
  tags               = var.tags
}

# Policy for Bedrock Agent to invoke Lambda
data "aws_iam_policy_document" "bedrock_agent_policy" {
  statement {
    effect = "Allow"
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = [
      aws_lambda_function.this.arn
    ]
  }
}

resource "aws_iam_role_policy" "bedrock_agent" {
  name   = "${var.agent_name}-bedrock-agent-policy"
  role   = aws_iam_role.bedrock_agent.id
  policy = data.aws_iam_policy_document.bedrock_agent_policy.json
}

# ==============================================================================
# Bedrock Agent Action Group (Lambda function)
# ==============================================================================

resource "aws_bedrock_agent_action_group" "lambda" {
  action_group_name     = "agent-handler"
  agent_id              = aws_bedrock_agent.this.agent_id
  agent_version         = "DRAFT"
  description           = "Lambda function handler for the agent"
  action_group_executor {
    lambda = aws_lambda_function.this.arn
  }
  api_schema {
    s3 {
      s3_bucket_name = aws_s3_bucket.agent_schema.bucket
      s3_object_key  = aws_s3_object.agent_schema.key
    }
  }
  depends_on = [
    aws_lambda_permission.bedrock_agent
  ]
}

# Lambda permission for Bedrock Agent to invoke
resource "aws_lambda_permission" "bedrock_agent" {
  statement_id  = "AllowBedrockAgentInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = "arn:aws:bedrock:${var.region}:*:agent/${aws_bedrock_agent.this.agent_id}/*"
}

# S3 bucket for agent API schema
resource "aws_s3_bucket" "agent_schema" {
  bucket        = "${var.function_name}-agent-schema-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "agent_schema" {
  bucket = aws_s3_bucket.agent_schema.id
  versioning_configuration {
    status = "Disabled"
  }
}

# API Schema for the agent (OpenAPI format)
resource "aws_s3_object" "agent_schema" {
  bucket  = aws_s3_bucket.agent_schema.bucket
  key     = "api-schema.json"
  content = jsonencode({
    openapi = "3.0.0"
    info = {
      title   = "RAG Agent API"
      version = "1.0.0"
    }
    paths = {
      "/invoke" = {
        post = {
          summary     = "Invoke the RAG agent"
          description = "Processes a query and returns a response using RAG"
          requestBody = {
            required = true
            content = {
              "application/json" = {
                schema = {
                  type       = "object"
                  required   = ["prompt", "tenant_id"]
                  properties = {
                    prompt = {
                      type        = "string"
                      description = "The user's query or prompt"
                    }
                    tenant_id = {
                      type        = "string"
                      description = "The tenant identifier"
                    }
                    agent_id = {
                      type        = "string"
                      description = "Optional agent identifier"
                    }
                  }
                }
              }
            }
          }
          responses = {
            "200" = {
              description = "Successful response"
              content = {
                "application/json" = {
                  schema = {
                    type = "object"
                    properties = {
                      statusCode = {
                        type = "number"
                      }
                      result = {
                        type = "string"
                      }
                      tenant_id = {
                        type = "string"
                      }
                      agent_id = {
                        type = "string"
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  })
}

data "aws_caller_identity" "current" {}

# ==============================================================================
# Bedrock Agent Alias
# ==============================================================================

resource "aws_bedrock_agent_alias" "this" {
  agent_id      = aws_bedrock_agent.this.agent_id
  agent_alias_name = "LIVE"
  description   = "Live alias for the agent"
}

# ==============================================================================
# CloudWatch Log Group
# ==============================================================================

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.this.function_name}"
  retention_in_days = 14
  tags              = var.tags
}

