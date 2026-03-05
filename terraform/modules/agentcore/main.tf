# ==============================================================================
# Bedrock AgentCore Module
# Based on: https://github.com/aws-ia/terraform-aws-agentcore
# ==============================================================================

terraform {
  required_version = ">= 1.0.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 0.24.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0"
    }
    time = {
      source  = "hashicorp/time"
      version = ">= 0.9.0"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.id

  # Different resources have different naming conventions:
  # - gateway: ^([0-9a-zA-Z][-]?){1,100}$ (use hyphens)
  # - runtime, endpoint, memory: ^[a-zA-Z][a-zA-Z0-9_]{0,47}$ (use underscores)
  name_with_hyphens     = replace(var.name_prefix, "_", "-")
  name_with_underscores = replace(var.name_prefix, "-", "_")

  runtime_name  = "${local.name_with_underscores}_runtime"
  endpoint_name = "${local.name_with_underscores}_endpoint"
  memory_name   = "${local.name_with_underscores}_memory"
  gateway_name  = "${local.name_with_hyphens}-gateway"

  common_tags = merge(var.tags, {
    Module      = "agentcore"
    Environment = var.environment
  })
}

# ==============================================================================
# Random suffix for unique names
# ==============================================================================

resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# ==============================================================================
# IAM Role for AgentCore Runtime
# ==============================================================================

resource "aws_iam_role" "runtime" {
  count = var.create_runtime && var.runtime_role_arn == null ? 1 : 0

  name = "${var.name_prefix}-runtime-role-${random_string.suffix.result}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "runtime" {
  count = var.create_runtime && var.runtime_role_arn == null ? 1 : 0

  name = "${var.name_prefix}-runtime-policy"
  role = aws_iam_role.runtime[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = ["arn:aws:bedrock:${local.region}::foundation-model/*"]
      },
      {
        Sid      = "LambdaInvoke"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = var.lambda_function_arns
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability"
        ]
        Resource = ["arn:aws:ecr:${local.region}:${local.account_id}:repository/*"]
      },
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:${local.region}:${local.account_id}:*"]
      },
      {
        Sid    = "XRay"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# Wait for IAM role propagation
resource "time_sleep" "runtime_iam_propagation" {
  count = var.create_runtime && var.runtime_role_arn == null ? 1 : 0

  depends_on      = [aws_iam_role_policy.runtime]
  create_duration = "15s"
}

# ==============================================================================
# Cognito User Pool for JWT Authentication
# ==============================================================================

resource "aws_cognito_user_pool" "this" {
  count = var.create_cognito ? 1 : 0

  name = "${var.name_prefix}-user-pool-${random_string.suffix.result}"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = var.cognito_password_policy.minimum_length
    require_lowercase = var.cognito_password_policy.require_lowercase
    require_uppercase = var.cognito_password_policy.require_uppercase
    require_numbers   = var.cognito_password_policy.require_numbers
    require_symbols   = var.cognito_password_policy.require_symbols
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  mfa_configuration = var.cognito_mfa_configuration

  tags = local.common_tags
}

resource "aws_cognito_user_pool_domain" "this" {
  count = var.create_cognito ? 1 : 0

  # Domain must be lowercase, numbers, and hyphens only: ^[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?$
  domain       = lower(replace("${var.name_prefix}-${random_string.suffix.result}", "_", "-"))
  user_pool_id = aws_cognito_user_pool.this[0].id
}

resource "aws_cognito_user_pool_client" "this" {
  count = var.create_cognito ? 1 : 0

  name         = "${var.name_prefix}-client"
  user_pool_id = aws_cognito_user_pool.this[0].id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH"
  ]

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.cognito_callback_urls
  logout_urls   = var.cognito_logout_urls

  access_token_validity  = var.cognito_token_validity_hours
  id_token_validity      = var.cognito_token_validity_hours
  refresh_token_validity = var.cognito_refresh_token_validity_days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

locals {
  cognito_discovery_url = var.create_cognito ? "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.this[0].id}/.well-known/openid-configuration" : var.cognito_discovery_url
  cognito_user_pool_id  = var.create_cognito ? aws_cognito_user_pool.this[0].id : var.cognito_user_pool_id
  cognito_client_id     = var.create_cognito ? aws_cognito_user_pool_client.this[0].id : var.cognito_client_id
}

# ==============================================================================
# AgentCore Runtime (Container-based)
# ==============================================================================

resource "awscc_bedrockagentcore_runtime" "this" {
  count = var.create_runtime ? 1 : 0

  agent_runtime_name = local.runtime_name
  description        = var.runtime_description

  role_arn = var.runtime_role_arn != null ? var.runtime_role_arn : aws_iam_role.runtime[0].arn

  agent_runtime_artifact = {
    container_configuration = {
      container_uri = var.runtime_container_uri
    }
  }

  network_configuration = {
    network_mode = var.runtime_network_mode
  }

  # Protocol configuration is a string value
  protocol_configuration = var.runtime_protocol

  environment_variables = var.runtime_environment_variables

  authorizer_configuration = var.create_cognito || var.cognito_discovery_url != null ? {
    custom_jwt_authorizer = {
      discovery_url    = local.cognito_discovery_url
      allowed_audience = length(var.cognito_allowed_audience) > 0 ? var.cognito_allowed_audience : [local.cognito_client_id]
      allowed_clients  = [local.cognito_client_id]
    }
  } : null

  lifecycle_configuration = {
    idle_runtime_session_timeout = var.runtime_idle_timeout
    max_lifetime                 = var.runtime_max_lifetime
  }

  tags = local.common_tags

  depends_on = [time_sleep.runtime_iam_propagation]
}

# ==============================================================================
# AgentCore Runtime Endpoint
# ==============================================================================

resource "awscc_bedrockagentcore_runtime_endpoint" "this" {
  count = var.create_runtime && var.create_runtime_endpoint ? 1 : 0

  name             = local.endpoint_name
  description      = "REST endpoint for ${var.name_prefix}"
  agent_runtime_id = awscc_bedrockagentcore_runtime.this[0].agent_runtime_id

  tags = local.common_tags
}

# ==============================================================================
# AgentCore Memory
# ==============================================================================

resource "aws_iam_role" "memory" {
  count = var.create_memory && var.memory_role_arn == null ? 1 : 0

  name = "${var.name_prefix}-memory-role-${random_string.suffix.result}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "memory_execution" {
  count = var.create_memory && var.memory_role_arn == null ? 1 : 0

  role       = aws_iam_role.memory[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockAgentCoreMemoryBedrockModelInferenceExecutionRolePolicy"
}

resource "time_sleep" "memory_iam_propagation" {
  count = var.create_memory && var.memory_role_arn == null ? 1 : 0

  depends_on      = [aws_iam_role_policy_attachment.memory_execution]
  create_duration = "15s"
}

resource "awscc_bedrockagentcore_memory" "this" {
  count = var.create_memory ? 1 : 0

  name        = local.memory_name
  description = var.memory_description

  event_expiry_duration = var.memory_event_expiry_days # Days (must be between 7 and 365)

  memory_execution_role_arn = var.memory_role_arn != null ? var.memory_role_arn : aws_iam_role.memory[0].arn

  encryption_key_arn = var.memory_kms_key_arn

  # Memory strategies
  memory_strategies = concat(
    # Short-term memory: Semantic strategy
    var.memory_enable_semantic ? [{
      semantic_memory_strategy = {
        name        = "semantic_${var.name_prefix}"
        description = "Semantic memory strategy for factual knowledge extraction"
        namespaces  = var.memory_semantic_namespaces
      }
    }] : [],

    # Short-term memory: Summary strategy
    var.memory_enable_summary ? [{
      summary_memory_strategy = {
        name        = "summary_${var.name_prefix}"
        description = "Summary memory strategy for conversation context"
        namespaces  = var.memory_summary_namespaces
      }
    }] : [],

    # Long-term memory: User preference strategy
    var.memory_enable_user_preference ? [{
      user_preference_memory_strategy = {
        name        = "preference_${var.name_prefix}"
        description = "User preference memory strategy for personalization"
        namespaces  = var.memory_user_preference_namespaces
      }
    }] : [],

    # Custom strategy with overrides (if provided)
    var.memory_custom_strategy != null ? [{
      custom_memory_strategy = var.memory_custom_strategy
    }] : []
  )

  tags = local.common_tags

  depends_on = [time_sleep.memory_iam_propagation]
}

# ==============================================================================
# AgentCore Gateway (API Gateway)
# ==============================================================================

resource "aws_iam_role" "gateway" {
  count = var.create_gateway && var.gateway_role_arn == null ? 1 : 0

  name = "${var.name_prefix}-gateway-role-${random_string.suffix.result}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "gateway" {
  count = var.create_gateway && var.gateway_role_arn == null ? 1 : 0

  name = "${var.name_prefix}-gateway-policy"
  role = aws_iam_role.gateway[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "LambdaInvoke"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = var.lambda_function_arns
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:${local.region}:${local.account_id}:*"]
      }
    ]
  })
}

resource "time_sleep" "gateway_iam_propagation" {
  count = var.create_gateway && var.gateway_role_arn == null ? 1 : 0

  depends_on      = [aws_iam_role_policy.gateway]
  create_duration = "15s"
}

resource "awscc_bedrockagentcore_gateway" "this" {
  count = var.create_gateway ? 1 : 0

  name        = local.gateway_name
  description = var.gateway_description

  role_arn = var.gateway_role_arn != null ? var.gateway_role_arn : aws_iam_role.gateway[0].arn

  protocol_type = "MCP"

  protocol_configuration = {
    mcp = {
      instructions       = var.gateway_instructions
      search_type        = var.gateway_search_type
      supported_versions = var.gateway_mcp_versions
    }
  }

  authorizer_type = var.create_cognito || var.cognito_discovery_url != null ? "CUSTOM_JWT" : "AWS_IAM"

  authorizer_configuration = var.create_cognito || var.cognito_discovery_url != null ? {
    custom_jwt_authorizer = {
      discovery_url    = local.cognito_discovery_url
      allowed_audience = length(var.cognito_allowed_audience) > 0 ? var.cognito_allowed_audience : [local.cognito_client_id]
      allowed_clients  = [local.cognito_client_id]
    }
  } : null

  kms_key_arn = var.gateway_kms_key_arn

  exception_level = var.gateway_exception_level

  tags = local.common_tags

  depends_on = [time_sleep.gateway_iam_propagation]
}

# ==============================================================================
# Gateway Target (connects Gateway to Lambda)
# Note: Gateway Target resource has complex schema that varies by provider version.
# For now, the gateway target can be created via AWS CLI after deployment:
#
# aws bedrock-agentcore create-gateway-target \
#   --gateway-identifier <gateway-id> \
#   --name "rag_agent_target" \
#   --target-configuration '{"mcp":{"lambda":{"lambdaArn":"<lambda-arn>"}}}' \
#   --credential-provider-configurations '[{"credentialProviderType":"GATEWAY_IAM_ROLE"}]'
# ==============================================================================

# Uncomment when provider schema is stable:
# resource "aws_bedrockagentcore_gateway_target" "this" {
#   count = var.create_gateway && var.create_gateway_target ? 1 : 0
#   gateway_identifier = awscc_bedrockagentcore_gateway.this[0].id
#   name               = "${var.name_prefix}_target"
#   ...
# }
