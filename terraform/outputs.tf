# ==============================================================================
# Aurora Outputs
# ==============================================================================

output "aurora_cluster_endpoint" {
  description = "Aurora cluster endpoint"
  value       = module.aurora.cluster_endpoint
}

output "aurora_reader_endpoint" {
  description = "Aurora reader endpoint"
  value       = module.aurora.reader_endpoint
}

output "aurora_security_group_id" {
  description = "Aurora security group ID"
  value       = module.aurora.security_group_id
}

# ==============================================================================
# S3 Outputs
# ==============================================================================

output "s3_documents_bucket_name" {
  description = "S3 documents bucket name"
  value       = module.s3_documents.bucket_name
}

output "s3_documents_bucket_arn" {
  description = "S3 documents bucket ARN"
  value       = module.s3_documents.bucket_arn
}

# ==============================================================================
# Lambda Outputs
# ==============================================================================

output "lambda_embeddings_function_name" {
  description = "Embeddings Lambda function name"
  value       = module.lambda_embeddings.function_name
}

output "lambda_embeddings_arn" {
  description = "Embeddings Lambda ARN"
  value       = module.lambda_embeddings.function_arn
}

output "lambda_query_function_name" {
  description = "Query Lambda function name"
  value       = module.lambda_query.function_name
}

output "lambda_query_arn" {
  description = "Query Lambda ARN"
  value       = module.lambda_query.function_arn
}

# ==============================================================================
# Usage Instructions
# ==============================================================================

output "upload_document_example" {
  description = "Example command to upload a document"
  value       = "aws s3 cp document.pdf s3://${module.s3_documents.bucket_name}/tenant_id/agent_id/document.pdf"
}

output "invoke_query_example" {
  description = "Example command to invoke query lambda"
  value       = <<-EOT
    aws lambda invoke \
      --function-name ${module.lambda_query.function_name} \
      --payload '{"query": "your question", "tenant_id": "your_tenant", "agent_id": "your_agent"}' \
      response.json
  EOT
}

# ==============================================================================
# Bedrock Agent Lambda Outputs
# ==============================================================================

output "bedrock_agent_lambda_function_name" {
  description = "Bedrock Agent Lambda function name"
  value       = module.bedrock_agent.lambda_function_name
}

output "bedrock_agent_lambda_arn" {
  description = "Bedrock Agent Lambda ARN"
  value       = module.bedrock_agent.lambda_function_arn
}

output "bedrock_agent_lambda_invoke_arn" {
  description = "Bedrock Agent Lambda Invoke ARN (for API Gateway integration)"
  value       = module.bedrock_agent.lambda_invoke_arn
}

# ==============================================================================
# API Gateway Outputs
# ==============================================================================

output "api_gateway_endpoint" {
  description = "API Gateway endpoint URL"
  value       = module.api_gateway.invoke_url
}

output "api_gateway_id" {
  description = "API Gateway ID"
  value       = module.api_gateway.api_id
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID for JWT authentication"
  value       = module.api_gateway.cognito_user_pool_id
}

output "cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID for JWT authentication"
  value       = module.api_gateway.cognito_user_pool_client_id
  sensitive   = false
}

# ==============================================================================
# API Usage Instructions
# ==============================================================================

output "api_usage_example" {
  description = "Example curl command to invoke the API"
  value       = <<-EOT
    # 1. Get JWT token from Cognito:
    TOKEN=$(aws cognito-idp initiate-auth \
      --auth-flow USER_PASSWORD_AUTH \
      --client-id ${module.api_gateway.cognito_user_pool_client_id} \
      --auth-parameters USERNAME=your-email@example.com,PASSWORD=YourPassword123! \
      --query 'AuthenticationResult.IdToken' \
      --output text)
    
    # 2. Invoke the API:
    curl -X POST ${module.api_gateway.invoke_url} \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "prompt": "¿Cuáles son los lineamientos de arquitectura?",
        "tenant_id": "your_tenant",
        "agent_id": "your_agent_id"
      }'
  EOT
}