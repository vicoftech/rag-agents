# EventBridge Scheduler → Lambda → StartExecution (Boletín / ANMAT).
# Ver variables enable_scheduled_boletin_anmat_sfn y scheduled_*_rag_agent_id.

module "scheduled_boletin_anmat_sfn" {
  count  = var.enable_scheduled_boletin_anmat_sfn ? 1 : 0
  source = "./modules/scheduled_boletin_anmat_sfn"

  name_prefix = "rag-${var.environment}"

  boletin_state_machine_arn = module.boletin_oficial_sfn.state_machine_arn
  anmat_state_machine_arn   = module.anmat_s3_stepfunction.state_machine_arn

  boletin_tenant_id = "boletin"
  boletin_agent_id  = var.scheduled_boletin_rag_agent_id

  anmat_tenant_id = "anmat"
  anmat_agent_id  = var.scheduled_anmat_rag_agent_id

  schedule_timezone = var.scheduled_sync_timezone

  tags = local.common_tags
}
