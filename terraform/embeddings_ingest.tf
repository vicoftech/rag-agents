# Cola S3 → encolador → SQS → rag_lmbd_embeddings-async (backpressure; sin S3 directo a embeddings).

resource "aws_sqs_queue" "embeddings_ingest_dlq" {
  name                      = "rag-embeddings-ingest-dlq-${var.environment}"
  message_retention_seconds = 1209600
  tags                      = local.common_tags
}

resource "aws_sqs_queue" "embeddings_ingest" {
  name = "rag-embeddings-ingest-${var.environment}"

  # >= 6× timeout Lambda (guía AWS para S→Lambda). Si timeout es 10s, 60s; fallas rápido y reintentos sin bloque 15 min.
  visibility_timeout_seconds = max(30, 6 * var.lambda_embeddings_config.timeout)
  message_retention_seconds  = 1209600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.embeddings_ingest_dlq.arn
    maxReceiveCount     = 5
  })

  tags = local.common_tags
}

module "lambda_embeddings_enqueue" {
  source = "./modules/lambda"

  function_name     = "rag_lmbd_embeddings_enqueue-${var.environment}"
  description       = "S3 -> SQS: encola ObjectCreated de PDFs para rag_lmbd_embeddings-async"
  handler           = "index.handler"
  runtime           = "python3.12"
  timeout           = 60
  memory_size       = 256
  source_path       = local.lambda_embeddings_enqueue_path
  environment       = var.environment
  use_s3_deployment = false

  environment_variables = {
    EMBEDDINGS_INGEST_QUEUE_URL = aws_sqs_queue.embeddings_ingest.url
  }

  attach_policy_statements = [
    {
      effect    = "Allow"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.embeddings_ingest.arn]
    }
  ]

  s3_trigger_enabled = false
  tags               = local.common_tags

  depends_on = [aws_sqs_queue.embeddings_ingest]
}

resource "aws_lambda_permission" "s3_invoke_embeddings_enqueue" {
  statement_id  = "AllowS3InvokeEmbeddingsEnqueue"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_embeddings_enqueue.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.documents_bucket_arn
}

# Una sola notificación para el bucket (encolador legacy y/o EventBridge para RAG v2).
resource "aws_s3_bucket_notification" "documents_to_embeddings_queue" {
  bucket = local.documents_bucket_name

  dynamic "lambda_function" {
    for_each = var.legacy_s3_embeddings_enqueue_enabled ? [1] : []
    content {
      id                  = "s3-embeddings-enqueue-pdf"
      lambda_function_arn = module.lambda_embeddings_enqueue.function_arn
      events              = ["s3:ObjectCreated:*"]
      filter_suffix       = ".pdf"
    }
  }

  eventbridge = var.s3_object_created_to_eventbridge

  depends_on = [module.lambda_embeddings_enqueue, aws_lambda_permission.s3_invoke_embeddings_enqueue]
}

output "embeddings_ingest_queue_url" {
  description = "SQS: PDFs a procesar (consumida por rag_lmbd_embeddings-async)"
  value       = aws_sqs_queue.embeddings_ingest.url
}

output "embeddings_ingest_queue_arn" {
  value = aws_sqs_queue.embeddings_ingest.arn
}

output "embeddings_ingest_dlq_url" {
  description = "DLQ de la cola de ingest (tras maxReceiveCount fallos; ver redrive en embeddings_ingest)"
  value       = aws_sqs_queue.embeddings_ingest_dlq.url
}

output "embeddings_ingest_dlq_arn" {
  value = aws_sqs_queue.embeddings_ingest_dlq.arn
}

output "lambda_embeddings_enqueue_function_name" {
  value = module.lambda_embeddings_enqueue.function_name
}
