output "api_id" {
  description = "ID of the API Gateway"
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Endpoint URL of the API Gateway"
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "invoke_url" {
  description = "Full URL for the /query endpoint"
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/${var.environment}/query"
}

output "authorizer_id" {
  description = "ID of the JWT authorizer"
  value       = aws_apigatewayv2_authorizer.jwt.id
}
