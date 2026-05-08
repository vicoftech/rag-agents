locals {
  task_families = {
    anmat   = "${var.project_name}-${var.environment}-anmat"
    boletin = "${var.project_name}-${var.environment}-boletin"
  }

  corridas_schedule = {
    anmat = {
      schedule_cron = var.schedule_cron_anmat
    }
    boletin = {
      schedule_cron = var.schedule_cron_boletin
    }
  }

  ecs_run_task_resources = [
    for k, fam in local.task_families :
    "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${fam}:*"
  ]
}
