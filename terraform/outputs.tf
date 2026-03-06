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
  value       = var.create_agentcore ? module.bedrock_agent[0].lambda_function_name : null
}

output "bedrock_agent_lambda_arn" {
  description = "Bedrock Agent Lambda ARN"
  value       = var.create_agentcore ? module.bedrock_agent[0].lambda_function_arn : null
}

output "bedrock_agent_lambda_invoke_arn" {
  description = "Bedrock Agent Lambda Invoke ARN (for API Gateway integration)"
  value       = var.create_agentcore ? module.bedrock_agent[0].lambda_invoke_arn : null
}

# ==============================================================================
# API Gateway Outputs
# ==============================================================================

output "api_gateway_endpoint" {
  description = "API Gateway endpoint URL"
  value       = var.create_agentcore ? module.api_gateway[0].invoke_url : null
}

output "query_api_gateway_endpoint" {
  description = "API Gateway endpoint URL for /query"
  value       = module.api_gateway_query.invoke_url
}

output "api_gateway_id" {
  description = "API Gateway ID"
  value       = var.create_agentcore ? module.api_gateway[0].api_id : null
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID for JWT authentication"
  value       = var.create_agentcore ? module.api_gateway[0].cognito_user_pool_id : null
}

output "cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID for JWT authentication"
  value       = var.create_agentcore ? module.api_gateway[0].cognito_user_pool_client_id : null
  sensitive   = false
}

output "query_cognito_user_pool_id" {
  description = "Cognito User Pool ID for /query JWT authentication"
  value       = module.cognito_query.user_pool_id
}

output "query_cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID for /query JWT authentication"
  value       = module.cognito_query.user_pool_client_id
  sensitive   = false
}

output "query_cognito_endpoint" {
  description = "Cognito issuer endpoint for /query JWT authentication"
  value       = module.cognito_query.cognito_endpoint
}

# ==============================================================================
# API Usage Instructions
# ==============================================================================

output "api_usage_example" {
  description = "Example curl command to invoke the API"
  value = var.create_agentcore ? (<<-EOT

    # 1. Get JWT token from Cognito:
    TOKEN=$(aws cognito-idp initiate-auth \
      --auth-flow USER_PASSWORD_AUTH \
      --client-id ${module.api_gateway[0].cognito_user_pool_client_id} \
      --auth-parameters USERNAME=your-email@example.com,PASSWORD=YourPassword123! \
      --query 'AuthenticationResult.IdToken' \
      --output text)
    
    # 2. Invoke the API:
    curl -X POST ${module.api_gateway[0].invoke_url} \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "prompt": "¿Cuáles son los lineamientos de arquitectura?",
        "tenant_id": "your_tenant",
        "agent_id": "your_agent_id"
      }'
  EOT
  ) : null
}

# ==============================================================================
# Lambda Parser Outputs
# ==============================================================================

output "lambda_parser_function_name" {
  description = "Name of the Lambda function"
  value       = module.lambda_parser.function_name
}

output "lambda_parser_function_arn" {
  description = "ARN of the Lambda function"
  value       = module.lambda_parser.function_arn
}

output "lambda_parser_invoke_arn" {
  description = "Invoke ARN of the Lambda function"
  value       = module.lambda_parser.invoke_arn
}

# ==============================================================================
# Lambda Fetcher Outputs
# ==============================================================================

output "lambda_fetcher_function_name" {
  description = "Name of the Lambda function"
  value       = module.lambda_fetcher.function_name
}

output "lambda_fetcher_function_arn" {
  description = "ARN of the Lambda function"
  value       = module.lambda_fetcher.function_arn
}

output "lambda_fetcher_invoke_arn" {
  description = "Invoke ARN of the Lambda function"
  value       = module.lambda_fetcher.invoke_arn
}

# ==============================================================================
# Bedrock AgentCore Outputs
# ==============================================================================

output "agentcore_runtime_id" {
  description = "AgentCore Runtime ID"
  value       = var.create_agentcore ? module.agentcore[0].runtime_id : null
}

output "agentcore_runtime_arn" {
  description = "AgentCore Runtime ARN"
  value       = var.create_agentcore ? module.agentcore[0].runtime_arn : null
}

output "agentcore_runtime_invoke_url" {
  description = "URL to invoke the AgentCore Runtime"
  value       = var.create_agentcore ? module.agentcore[0].runtime_invoke_url : null
}

output "agentcore_runtime_endpoint_id" {
  description = "AgentCore Runtime Endpoint ID"
  value       = var.create_agentcore ? module.agentcore[0].runtime_endpoint_id : null
}

output "agentcore_cognito_user_pool_id" {
  description = "Cognito User Pool ID for AgentCore"
  value       = var.create_agentcore ? module.agentcore[0].cognito_user_pool_id : null
}

output "agentcore_cognito_client_id" {
  description = "Cognito Client ID for AgentCore"
  value       = var.create_agentcore ? module.agentcore[0].cognito_client_id : null
}

output "agentcore_cognito_token_url" {
  description = "URL to obtain tokens from Cognito"
  value       = var.create_agentcore ? module.agentcore[0].cognito_token_url : null
}

output "agentcore_memory_id" {
  description = "AgentCore Memory ID"
  value       = var.create_agentcore ? module.agentcore[0].memory_id : null
}

output "agentcore_gateway_id" {
  description = "AgentCore Gateway ID"
  value       = var.create_agentcore ? module.agentcore[0].gateway_id : null
}

output "agentcore_gateway_url" {
  description = "AgentCore Gateway URL"
  value       = var.create_agentcore ? module.agentcore[0].gateway_url : null
}

output "agentcore_usage_instructions" {
  description = "Instructions for using AgentCore"
  value       = var.create_agentcore ? module.agentcore[0].usage_instructions : null
}