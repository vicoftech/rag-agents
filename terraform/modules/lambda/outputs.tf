output "function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.this.arn
}

output "invoke_arn" {
  description = "Lambda invoke ARN"
  value       = aws_lambda_function.this.invoke_arn
}

output "role_arn" {
  description = "Lambda IAM role ARN"
  value       = aws_iam_role.lambda.arn
}

output "role_name" {
  description = "Lambda IAM role name"
  value       = aws_iam_role.lambda.name
}

output "security_group_id" {
  description = "Lambda security group ID (if created)"
  value       = length(aws_security_group.lambda) > 0 ? aws_security_group.lambda[0].id : null
}

output "log_group_name" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.lambda.name
}
