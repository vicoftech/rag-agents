locals {
  # El ARN del dispatcher suele ser (known after apply) en el primer ciclo:
  # el count debe depender sólo del flag explícito.
  dispatch_enabled = var.enable_query_dispatcher
}

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

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.this.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${var.api_name}-jwt-authorizer"

  jwt_configuration {
    audience = [var.cognito_user_pool_client_id]
    issuer   = var.cognito_endpoint
  }
}

# Worker (presigned URL + modo sync si dispatcher deshabilitado)
resource "aws_lambda_permission" "api_gateway_worker" {
  statement_id  = "AllowAPIGatewayInvokeQuery"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "worker" {
  api_id                   = aws_apigatewayv2_api.this.id
  integration_type         = "AWS_PROXY"
  integration_uri          = var.lambda_invoke_arn
  payload_format_version   = "2.0"
  timeout_milliseconds     = 30000
}

# Dispatcher (consulta async corta): sólo cuando se pasa ARN
resource "aws_lambda_permission" "api_gateway_dispatcher" {
  count = local.dispatch_enabled ? 1 : 0

  statement_id  = "AllowAPIGatewayInvokeQueryDispatcher"
  action          = "lambda:InvokeFunction"
  function_name   = var.dispatcher_lambda_function_name
  principal       = "apigateway.amazonaws.com"
  source_arn      = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "dispatcher" {
  count = local.dispatch_enabled ? 1 : 0

  api_id                   = aws_apigatewayv2_api.this.id
  integration_type         = "AWS_PROXY"
  integration_uri          = var.dispatcher_lambda_invoke_arn
  payload_format_version   = "2.0"
  timeout_milliseconds     = 30000
}

# POST /query: dispatcher si existe; si no, worker síncrono
resource "aws_apigatewayv2_route" "query" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "POST /query"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  target             = local.dispatch_enabled ? "integrations/${aws_apigatewayv2_integration.dispatcher[0].id}" : "integrations/${aws_apigatewayv2_integration.worker.id}"
}

resource "aws_apigatewayv2_route" "query_options" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "OPTIONS /query"
  authorization_type = "NONE"
  target             = local.dispatch_enabled ? "integrations/${aws_apigatewayv2_integration.dispatcher[0].id}" : "integrations/${aws_apigatewayv2_integration.worker.id}"
}

resource "aws_apigatewayv2_route" "query_status" {
  count = local.dispatch_enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "GET /query/status/{id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  target             = "integrations/${aws_apigatewayv2_integration.dispatcher[0].id}"
}

resource "aws_apigatewayv2_route" "query_status_options" {
  count = local.dispatch_enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "OPTIONS /query/status/{id}"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.dispatcher[0].id}"
}

resource "aws_apigatewayv2_route" "query_result" {
  count = local.dispatch_enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "GET /query/result/{id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  target             = "integrations/${aws_apigatewayv2_integration.dispatcher[0].id}"
}

resource "aws_apigatewayv2_route" "query_result_options" {
  count = local.dispatch_enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "OPTIONS /query/result/{id}"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.dispatcher[0].id}"
}

resource "aws_apigatewayv2_route" "presigned_url" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "GET /presigned-url"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
}

resource "aws_apigatewayv2_route" "presigned_url_options" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "OPTIONS /presigned-url"
  authorization_type = "NONE"
  target             = "integrations/${aws_apigatewayv2_integration.worker.id}"
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${var.api_name}"
  retention_in_days = 14
  tags              = var.tags
}

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

  tags = var.tags
}
