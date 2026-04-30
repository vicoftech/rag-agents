# ==============================================================================
# Aurora Outputs
# ==============================================================================

output "aurora_cluster_endpoint" {
  description = "Hostname writer (lectura/escritura). En Aurora, cluster.endpoint ES el host writer (-h en psql)."
  value       = var.create_aurora_cluster ? module.aurora[0].cluster_endpoint : var.existing_db_host
}

output "aurora_writer_host" {
  description = "Igual que aurora_cluster_endpoint (writer)."
  value       = var.create_aurora_cluster ? module.aurora[0].writer_endpoint : var.existing_db_host
}

output "aurora_reader_endpoint" {
  description = "Hostname reader (solo lectura)."
  value       = var.create_aurora_cluster ? module.aurora[0].reader_endpoint : null
}

output "aurora_reader_host" {
  description = "Alias de aurora_reader_endpoint."
  value       = var.create_aurora_cluster ? module.aurora[0].reader_endpoint : null
}

output "aurora_security_group_id" {
  description = "Aurora security group ID"
  value       = var.create_aurora_cluster ? module.aurora[0].security_group_id : var.existing_db_security_group_id
}

output "rag_lambda_security_group_id" {
  description = "Security group for VPC Lambdas (embeddings, query, agent): egress a S3/APIs; no usar el SG de RDS en Lambdas"
  value       = local.rag_lambda_security_group_id
}

# ==============================================================================
# S3 Outputs
# ==============================================================================

output "rag_ingestion_state_machine_arn" {
  description = "Step Functions RAG v2: alert-rag-ingestion (requiere create_rag_ingestion)"
  value       = var.create_rag_ingestion ? module.rag_ingestion[0].state_machine_arn : null
}

output "s3_documents_bucket_name" {
  description = "S3 documents bucket name"
  value       = local.documents_bucket_name
}

output "s3_documents_bucket_arn" {
  description = "S3 documents bucket ARN"
  value       = local.documents_bucket_arn
}

# ==============================================================================
# Lambda Outputs
# ==============================================================================

output "lambda_embeddings_function_name" {
  description = "Embeddings Lambda function name (rag_lmbd_embeddings-async)"
  value       = module.lambda_embeddings_async.function_name
}

output "lambda_embeddings_arn" {
  description = "Embeddings Lambda ARN"
  value       = module.lambda_embeddings_async.function_arn
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
  description = "Example command to upload a document (key must include /documents/ after agent UUID)"
  value       = "aws s3 cp document.pdf s3://${local.documents_bucket_name}/tenant_boletin/<agent-uuid>/documents/20260310/primera/archivo.pdf"
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

output "query_presigned_url_endpoint" {
  description = "API Gateway URL for GET /presigned-url?key=<s3-object-key> (JWT same as /query)"
  value       = module.api_gateway_query.presigned_url_invoke_url
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
# DynamoDB Outputs
# ==============================================================================

output "dynamodb_documents_table_name" {
  description = "DynamoDB documents table name"
  value       = aws_dynamodb_table.documents.name
}

output "dynamodb_documents_table_arn" {
  description = "DynamoDB documents table ARN"
  value       = aws_dynamodb_table.documents.arn
}

# ==============================================================================
# SNS Topic Outputs
# ==============================================================================

output "sns_topic_arn" {
  description = "SNS topic ARN for notifications"
  value       = aws_sns_topic.rag_notifications.arn
}

output "sns_topic_name" {
  description = "SNS topic name for notifications"
  value       = aws_sns_topic.rag_notifications.name
}

# ==============================================================================
# Lambda Notifier Outputs
# ==============================================================================

output "lambda_notifier_function_name" {
  description = "Name of Lambda function"
  value       = module.lambda_notifier.function_name
}

output "lambda_notifier_function_arn" {
  description = "ARN of Lambda function"
  value       = module.lambda_notifier.function_arn
}

output "lambda_notifier_invoke_arn" {
  description = "Invoke ARN of Lambda function"
  value       = module.lambda_notifier.invoke_arn
}

# ==============================================================================
# Lambda DBWriter Outputs
# ==============================================================================

output "lambda_dbwriter_function_name" {
  description = "Name of Lambda function"
  value       = module.lambda_dbwriter.function_name
}

output "lambda_dbwriter_function_arn" {
  description = "ARN of Lambda function"
  value       = module.lambda_dbwriter.function_arn
}

output "lambda_dbwriter_invoke_arn" {
  description = "Invoke ARN of Lambda function"
  value       = module.lambda_dbwriter.invoke_arn
}

# ==============================================================================
# Lambda S3Writer Outputs
# ==============================================================================

output "lambda_s3writer_function_name" {
  description = "Name of the Lambda function"
  value       = module.lambda_s3writer.function_name
}

output "lambda_s3writer_function_arn" {
  description = "ARN of the Lambda function"
  value       = module.lambda_s3writer.function_arn
}

output "lambda_s3writer_invoke_arn" {
  description = "Invoke ARN of the Lambda function"
  value       = module.lambda_s3writer.invoke_arn
}

output "alert_s3writer_sqs_queue_url" {
  description = "URL of the SQS queue that triggers rag_lmbd_s3writer"
  value       = aws_sqs_queue.alert_s3writer.url
}

output "alert_s3writer_sqs_queue_arn" {
  description = "ARN of the SQS queue that triggers rag_lmbd_s3writer"
  value       = aws_sqs_queue.alert_s3writer.arn
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