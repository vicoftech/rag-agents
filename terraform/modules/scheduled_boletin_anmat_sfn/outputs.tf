output "lambda_function_name" {
  value = aws_lambda_function.runner.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.runner.arn
}

output "schedule_group_name" {
  value = aws_scheduler_schedule_group.this.name
}

output "schedule_boletin_arn" {
  value = aws_scheduler_schedule.boletin.arn
}

output "schedule_anmat_arn" {
  value = aws_scheduler_schedule.anmat.arn
}
