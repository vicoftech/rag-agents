output "state_machine_arn" {
  description = "ARN del state machine de Boletín (bolinks → s3writer → dbwriter, JSONata)"
  value       = aws_sfn_state_machine.boletin.arn
}

output "state_machine_name" {
  value = aws_sfn_state_machine.boletin.name
}
