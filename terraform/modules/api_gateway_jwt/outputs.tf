output "api_id" {
  description = "ID of the API Gateway"
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Endpoint URL of the API Gateway"
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "invoke_url" {
  description = "Full URL for the /invoke endpoint"
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/${var.environment}/invoke"
}

output "cognito_user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = local.user_pool_id
}

output "cognito_user_pool_arn" {
  description = "ARN of the Cognito User Pool"
  value       = local.user_pool_arn
}

output "cognito_user_pool_client_id" {
  description = "ID of the Cognito User Pool Client"
  value       = local.user_pool_client_id
}

output "authorizer_id" {
  description = "ID of the JWT authorizer"
  value       = aws_apigatewayv2_authorizer.jwt.id
}



