# ==============================================================================
# Cognito User Pool (if not provided)
# ==============================================================================

resource "aws_cognito_user_pool" "this" {
  count = var.create_cognito_user_pool ? 1 : 0
  name  = "${var.api_name}-user-pool-${var.environment}"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
  }

  tags = var.tags
}

resource "aws_cognito_user_pool_client" "this" {
  count        = var.create_cognito_user_pool ? 1 : 0
  name         = "${var.api_name}-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.this[0].id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["implicit"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["https://localhost"]

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  access_token_validity  = 24
  id_token_validity      = 24
  refresh_token_validity = 30
}

# Use provided or created resources
locals {
  user_pool_id     = var.create_cognito_user_pool ? aws_cognito_user_pool.this[0].id : var.cognito_user_pool_id
  user_pool_arn    = var.create_cognito_user_pool ? aws_cognito_user_pool.this[0].arn : var.cognito_user_pool_arn
  user_pool_client_id = var.create_cognito_user_pool ? aws_cognito_user_pool_client.this[0].id : var.cognito_user_pool_client_id
}

# ==============================================================================
# API Gateway REST API
# ==============================================================================

resource "aws_apigatewayv2_api" "this" {
  name          = var.api_name
  description   = var.api_description
  protocol_type = "HTTP"
  version       = "1.0"

  cors_configuration {
    allow_origins = var.cors_allowed_origins
    allow_methods = var.cors_allowed_methods
    allow_headers = var.cors_allowed_headers
    max_age       = 300
  }

  tags = var.tags
}

# ==============================================================================
# JWT Authorizer
# ==============================================================================

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.this.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.api_name}-jwt-authorizer"

  jwt_configuration {
    audience = [local.user_pool_client_id]
    issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${local.user_pool_id}"
  }
}

# ==============================================================================
# Lambda Permission for API Gateway
# ==============================================================================

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# ==============================================================================
# API Gateway Integration with Lambda
# ==============================================================================

resource "aws_apigatewayv2_integration" "lambda" {
  api_id           = aws_apigatewayv2_api.this.id
  integration_type = "AWS_PROXY"
  integration_uri  = var.lambda_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds = 30000
}

# ==============================================================================
# API Gateway Routes
# ==============================================================================

# POST /invoke - Invoke the agent
resource "aws_apigatewayv2_route" "invoke" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /invoke"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorizer_id = aws_apigatewayv2_authorizer.jwt.id
  authorization_type = "JWT"
}

# OPTIONS /invoke - CORS preflight
resource "aws_apigatewayv2_route" "invoke_options" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "OPTIONS /invoke"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# ==============================================================================
# API Gateway Stage
# ==============================================================================

resource "aws_apigatewayv2_stage" "this" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = var.environment
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }

  default_route_settings {
    detailed_metrics_enabled = true
    throttling_burst_limit   = 100
    throttling_rate_limit    = 50
  }

  tags = var.tags
}

# ==============================================================================
# CloudWatch Log Group for API Gateway
# ==============================================================================

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${var.api_name}"
  retention_in_days = 14
  tags              = var.tags
}

# ==============================================================================
# API Gateway Deployment
# ==============================================================================

resource "aws_apigatewayv2_deployment" "this" {
  api_id = aws_apigatewayv2_api.this.id

  depends_on = [
    aws_apigatewayv2_route.invoke,
    aws_apigatewayv2_route.invoke_options,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

