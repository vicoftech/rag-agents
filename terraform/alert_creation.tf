# ==============================================================================
# Alert creation: SQS → Lambda (PostgreSQL public.* + lectura tenant_anmat.documents)
# ==============================================================================

locals {
  alert_creation_enabled = var.enable_alert_creation_lambda
}

resource "aws_sqs_queue" "rag_alert_creation_dlq" {
  count = local.alert_creation_enabled ? 1 : 0

  name = "rag-alert-creation-dlq-${var.environment}"
  tags = merge(local.common_tags, {
    Name = "rag-alert-creation-dlq-${var.environment}"
  })
}

resource "aws_sqs_queue" "rag_alert_creation" {
  count = local.alert_creation_enabled ? 1 : 0

  name                       = "rag-alert-creation-${var.environment}"
  visibility_timeout_seconds = 360
  receive_wait_time_seconds  = 0

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.rag_alert_creation_dlq[0].arn
    maxReceiveCount     = 3
  })

  tags = merge(local.common_tags, {
    Name = "rag-alert-creation-${var.environment}"
  })
}

module "lambda_alert_creation" {
  count  = local.alert_creation_enabled ? 1 : 0
  source = "./modules/lambda"

  function_name          = "rag_lmbd_alert_creation-${var.environment}"
  description            = "SQS: crea alerta en public.alerta_generada, disposicion, disposicion_contenido (chunks tenant_anmat)"
  handler                = "handler.handler"
  runtime                = "python3.12"
  timeout                = 120
  memory_size            = 512
  ephemeral_storage_size = 512

  source_path = "${path.module}/../apps/rag_lmbd_alert_creation"
  environment = var.environment

  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = [local.rag_lambda_security_group_id]

  use_s3_deployment = true
  s3_bucket_name    = local.documents_bucket_name

  sqs_trigger_enabled            = true
  sqs_queue_arn                  = aws_sqs_queue.rag_alert_creation[0].arn
  sqs_batch_size                 = 5
  sqs_report_batch_item_failures = true

  environment_variables = merge(
    var.db_secret_id != "" ? { DB_SECRET_ARN = var.db_secret_id } : {},
    var.db_secret_id == "" ? {
      DB_HOST     = local.db_host
      DB_PORT     = local.db_port
      DB_NAME     = local.db_name
      DB_USER     = var.master_username
      DB_PASSWORD = var.master_password
    } : {},
  )

  attach_policy_statements = concat(
    local.lambda_db_secret_policy,
    [],
  )

  tags = local.common_tags
}
