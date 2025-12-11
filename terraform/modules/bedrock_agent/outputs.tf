output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.this.arn
}

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.this.function_name
}

output "agent_id" {
  description = "ID of the Bedrock Agent"
  value       = aws_bedrock_agent.this.agent_id
}

output "agent_arn" {
  description = "ARN of the Bedrock Agent"
  value       = aws_bedrock_agent.this.agent_arn
}

output "agent_alias_id" {
  description = "ID of the Bedrock Agent alias"
  value       = aws_bedrock_agent_alias.this.agent_alias_id
}

output "agent_alias_arn" {
  description = "ARN of the Bedrock Agent alias"
  value       = aws_bedrock_agent_alias.this.agent_alias_arn
}



