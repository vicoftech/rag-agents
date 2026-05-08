resource "aws_scheduler_schedule_group" "batch" {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_scheduler_schedule" "batch" {
  for_each = local.corridas_schedule

  name        = "${var.project_name}-${each.key}-${var.environment}"
  description = "alerts_semantic_matches.py prod — corrida ${each.key} (full corpus, SQS email + alert creation)"
  group_name  = aws_scheduler_schedule_group.batch.name
  state       = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = each.value.schedule_cron

  target {
    arn      = aws_ecs_cluster.batch.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.batch[each.key].arn_without_revision
      task_count          = 1
      launch_type         = "FARGATE"
      platform_version    = "LATEST"

      network_configuration {
        subnets          = var.private_subnet_ids
        security_groups  = [aws_security_group.batch.id]
        assign_public_ip = var.assign_public_ip
      }
    }
  }
}
