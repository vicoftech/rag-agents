output "api_id" {
  description = "ID of the API Gateway"
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Hostname base (`https://<api-id>.execute-api.<region>.amazonaws.com`)"
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "stage_environment" {
  description = "Nombre del stage (p. ej. qa, prod) — sufijo URL."
  value       = var.environment
}

output "invoke_url" {
  description = "Full URL for the /query endpoint"
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/${var.environment}/query"
}

output "presigned_url_invoke_url" {
  description = "Base path for GET /presigned-url (append ?key=<object-key>)"
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/${var.environment}/presigned-url"
}

output "authorizer_id" {
  description = "ID of the JWT authorizer"
  value       = aws_apigatewayv2_authorizer.jwt.id
}
