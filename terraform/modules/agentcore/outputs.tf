# ==============================================================================
# Runtime Outputs
# ==============================================================================

output "runtime_id" {
  description = "ID of the AgentCore Runtime"
  value       = var.create_runtime ? awscc_bedrockagentcore_runtime.this[0].agent_runtime_id : null
}

output "runtime_arn" {
  description = "ARN of the AgentCore Runtime"
  value       = var.create_runtime ? awscc_bedrockagentcore_runtime.this[0].agent_runtime_arn : null
}

output "runtime_status" {
  description = "Status of the AgentCore Runtime"
  value       = var.create_runtime ? awscc_bedrockagentcore_runtime.this[0].status : null
}

output "runtime_role_arn" {
  description = "ARN of the IAM role used by the Runtime"
  value       = var.create_runtime ? (var.runtime_role_arn != null ? var.runtime_role_arn : aws_iam_role.runtime[0].arn) : null
}

output "runtime_invoke_url" {
  description = "URL to invoke the AgentCore Runtime"
  value       = var.create_runtime ? "https://bedrock-agentcore.${data.aws_region.current.id}.amazonaws.com/runtimes/${awscc_bedrockagentcore_runtime.this[0].agent_runtime_arn}/invocations" : null
}

# ==============================================================================
# Runtime Endpoint Outputs
# ==============================================================================

output "runtime_endpoint_id" {
  description = "ID of the AgentCore Runtime Endpoint"
  value       = var.create_runtime && var.create_runtime_endpoint ? awscc_bedrockagentcore_runtime_endpoint.this[0].id : null
}

output "runtime_endpoint_arn" {
  description = "ARN of the AgentCore Runtime Endpoint"
  value       = var.create_runtime && var.create_runtime_endpoint ? awscc_bedrockagentcore_runtime_endpoint.this[0].agent_runtime_endpoint_arn : null
}

output "runtime_endpoint_status" {
  description = "Status of the AgentCore Runtime Endpoint"
  value       = var.create_runtime && var.create_runtime_endpoint ? awscc_bedrockagentcore_runtime_endpoint.this[0].status : null
}

# ==============================================================================
# Cognito Outputs
# ==============================================================================

output "cognito_user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = var.create_cognito ? aws_cognito_user_pool.this[0].id : var.cognito_user_pool_id
}

output "cognito_user_pool_arn" {
  description = "ARN of the Cognito User Pool"
  value       = var.create_cognito ? aws_cognito_user_pool.this[0].arn : null
}

output "cognito_user_pool_endpoint" {
  description = "Endpoint of the Cognito User Pool"
  value       = var.create_cognito ? aws_cognito_user_pool.this[0].endpoint : null
}

output "cognito_client_id" {
  description = "ID of the Cognito User Pool Client"
  value       = var.create_cognito ? aws_cognito_user_pool_client.this[0].id : var.cognito_client_id
}

output "cognito_domain" {
  description = "Domain of the Cognito User Pool"
  value       = var.create_cognito ? aws_cognito_user_pool_domain.this[0].domain : null
}

output "cognito_discovery_url" {
  description = "OIDC Discovery URL"
  value       = local.cognito_discovery_url
}

output "cognito_token_url" {
  description = "URL to obtain tokens from Cognito"
  value       = var.create_cognito ? "https://${aws_cognito_user_pool_domain.this[0].domain}.auth.${data.aws_region.current.id}.amazoncognito.com/oauth2/token" : null
}

# ==============================================================================
# Memory Outputs
# ==============================================================================

output "memory_id" {
  description = "ID of the AgentCore Memory"
  value       = var.create_memory ? awscc_bedrockagentcore_memory.this[0].memory_id : null
}

output "memory_arn" {
  description = "ARN of the AgentCore Memory"
  value       = var.create_memory ? awscc_bedrockagentcore_memory.this[0].memory_arn : null
}

output "memory_status" {
  description = "Status of the AgentCore Memory"
  value       = var.create_memory ? awscc_bedrockagentcore_memory.this[0].status : null
}

output "memory_role_arn" {
  description = "ARN of the IAM role used by Memory"
  value       = var.create_memory ? (var.memory_role_arn != null ? var.memory_role_arn : aws_iam_role.memory[0].arn) : null
}

# ==============================================================================
# Gateway Outputs
# ==============================================================================

output "gateway_id" {
  description = "ID of the AgentCore Gateway"
  value       = var.create_gateway ? awscc_bedrockagentcore_gateway.this[0].id : null
}

output "gateway_arn" {
  description = "ARN of the AgentCore Gateway"
  value       = var.create_gateway ? awscc_bedrockagentcore_gateway.this[0].gateway_arn : null
}

output "gateway_url" {
  description = "URL of the AgentCore Gateway"
  value       = var.create_gateway ? awscc_bedrockagentcore_gateway.this[0].gateway_url : null
}

output "gateway_status" {
  description = "Status of the AgentCore Gateway"
  value       = var.create_gateway ? awscc_bedrockagentcore_gateway.this[0].status : null
}

output "gateway_role_arn" {
  description = "ARN of the IAM role used by Gateway"
  value       = var.create_gateway ? (var.gateway_role_arn != null ? var.gateway_role_arn : aws_iam_role.gateway[0].arn) : null
}

# ==============================================================================
# Gateway Target Outputs
# ==============================================================================

output "gateway_target_id" {
  description = "ID of the Gateway Target (create via AWS CLI after deployment)"
  value       = null  # Gateway target must be created via AWS CLI due to provider schema limitations
}

# ==============================================================================
# Usage Instructions
# ==============================================================================

output "usage_instructions" {
  description = "Instructions for using the deployed AgentCore"
  value       = <<-EOT
    
    ================================================================================
    AgentCore Deployment Complete
    ================================================================================
    
    Runtime ARN: ${var.create_runtime ? awscc_bedrockagentcore_runtime.this[0].agent_runtime_arn : "N/A"}
    
    ================================================================================
    Authentication (Cognito):
    ================================================================================
    
    1. Get a token:
       
       aws cognito-idp initiate-auth \
         --auth-flow USER_PASSWORD_AUTH \
         --client-id ${local.cognito_client_id} \
         --auth-parameters USERNAME=your-email@example.com,PASSWORD=YourPassword123!
    
    ================================================================================
    Invoke the Agent (with awscurl):
    ================================================================================
    
    pip install awscurl
    
    awscurl --service bedrock-agentcore \
      --region ${data.aws_region.current.id} \
      -X POST "${var.create_runtime ? "https://bedrock-agentcore.${data.aws_region.current.id}.amazonaws.com/runtimes/${awscc_bedrockagentcore_runtime.this[0].agent_runtime_arn}/invocations" : "N/A"}" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Your question here"}'
    
    ================================================================================
    Gateway URL (if created):
    ================================================================================
    
    ${var.create_gateway ? awscc_bedrockagentcore_gateway.this[0].gateway_url : "N/A"}
    
  EOT
}
