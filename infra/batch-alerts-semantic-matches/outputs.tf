output "ecr_repository_url" {
  description = "URL para docker push después del primer apply."
  value       = aws_ecr_repository.batch.repository_url
}

output "ecr_anmat_s3_rekey_repository_url" {
  description = "ECR imagen batch/anmat-s3-rekey (CI batch-anmat-s3-rekey-docker.yml)"
  value       = aws_ecr_repository.anmat_s3_rekey.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.batch.name
}

output "schedule_names" {
  value = [for k, s in aws_scheduler_schedule.batch : s.name]
}

output "schedule_expressions" {
  value = {
    for k, s in aws_scheduler_schedule.batch : k => s.schedule_expression
  }
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.batch.name
}

output "github_actions_ecr_role_arn" {
  description = "Pegalo en GitHub Secret AWS_BATCH_ECR_ROLE_ARN"
  value       = aws_iam_role.github_ecr_batch.arn
}

output "github_actions_lambda_deploy_role_arn" {
  description = "Mismo ARN que AWS_BATCH_ECR_ROLE_ARN — rol con ECR + Lambda deploy (policy lambda-deploy-rag-lmbd)."
  value       = aws_iam_role.github_ecr_batch.arn
}

output "github_oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}
