# EventBridge Scheduler → Lambda → StartExecution (Boletín / ANMAT).
# Ver variables enable_scheduled_boletin_anmat_sfn y scheduled_*_rag_agent_id.
# data.aws_caller_identity.current / data.aws_region.current: definidos en main.tf

locals {
  scheduled_boletin_sfn_arn = (
    trimspace(var.scheduled_boletin_sfn_arn_override) != ""
    ? trimspace(var.scheduled_boletin_sfn_arn_override)
    : module.boletin_oficial_sfn.state_machine_arn
  )
}

module "scheduled_boletin_anmat_sfn" {
  count  = var.enable_scheduled_boletin_anmat_sfn ? 1 : 0
  source = "./modules/scheduled_boletin_anmat_sfn"

  name_prefix = "rag-${var.environment}"

  boletin_state_machine_arn = local.scheduled_boletin_sfn_arn
  boletin_state_machine_arns_extra = compact([
    module.boletin_oficial_sfn.state_machine_arn != local.scheduled_boletin_sfn_arn
    ? module.boletin_oficial_sfn.state_machine_arn
    : "",
    "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:Alerts-BoletinOficialSyncronizer-prod",
  ])
  anmat_state_machine_arn = module.anmat_s3_stepfunction.state_machine_arn
  # Mismo patrón que Boletín: principal + extras vía boletin_state_machine_arns_extra; ANMAT prod usa rag-anmat-to-s3writer-prod.

  boletin_tenant_id        = var.scheduled_boletin_tenant_id
  boletin_agent_id         = var.scheduled_boletin_rag_agent_id
  boletin_cron_minute_hour = var.scheduled_boletin_cron_minute_hour

  anmat_tenant_id          = "anmat"
  anmat_agent_id           = var.scheduled_anmat_rag_agent_id
  anmat_cron_minute_hour   = var.scheduled_anmat_cron_minute_hour

  schedule_timezone = var.scheduled_sync_timezone

  tags = local.common_tags
}
