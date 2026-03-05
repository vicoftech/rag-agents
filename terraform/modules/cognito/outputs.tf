output "user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_client_id" {
  description = "Cognito User Pool Client ID"
  value       = aws_cognito_user_pool_client.this.id
}

output "cognito_endpoint" {
  description = "Cognito issuer endpoint (used as JWT issuer)"
  value       = local.cognito_endpoint
}
