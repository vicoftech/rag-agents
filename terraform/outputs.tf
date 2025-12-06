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
