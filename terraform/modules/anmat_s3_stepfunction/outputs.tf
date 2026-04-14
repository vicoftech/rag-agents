output "state_machine_arn" {
  description = "ARN of the anmat → S3 writer pipeline state machine"
  value       = aws_sfn_state_machine.anmat_to_s3.arn
}

output "state_machine_name" {
  description = "Name of the state machine"
  value       = aws_sfn_state_machine.anmat_to_s3.name
}

output "execution_role_arn" {
  description = "IAM role used by the state machine"
  value       = aws_iam_role.sfn.arn
}
