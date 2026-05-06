locals {
  async_rag = var.enable_async_rag_query
}

# ----- DynamoDB resultado / caché de jobs -----
resource "aws_dynamodb_table" "rag_result_query_table" {
  count = local.async_rag ? 1 : 0

  name         = "rag_result_query_table-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "S"
  }
  attribute {
    name = "tenant_id"
    type = "S"
  }
  attribute {
    name = "agent_id"
    type = "S"
  }
  attribute {
    name = "query"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }
  attribute {
    name = "start_at"
    type = "S"
  }
  attribute {
    name = "start_end"
    type = "S"
  }

  dynamic "global_secondary_index" {
    for_each = {
      gsi_status_created_at = {
        hash_key        = "status"
        range_key       = "created_at"
      }
      gsi_query_created_at = {
        hash_key        = "query"
        range_key       = "created_at"
      }
      gsi_agent_id_created_at = {
        hash_key        = "agent_id"
        range_key     = "created_at"
      }
      gsi_tenant_id_created_at = {
        hash_key        = "tenant_id"
        range_key     = "created_at"
      }
      gsi_start_at_created_at = {
        hash_key        = "start_at"
        range_key     = "created_at"
      }
      gsi_start_end_created_at = {
        hash_key        = "start_end"
        range_key     = "created_at"
      }
    }
    content {
      name               = global_secondary_index.key
      hash_key           = global_secondary_index.value.hash_key
      range_key          = global_secondary_index.value.range_key
      projection_type    = "ALL"
    }
  }

  tags = merge(local.common_tags, {
    Name = "rag_result_query_table-${var.environment}"
  })
}

resource "aws_sqs_queue" "rag_query_documents_dlq" {
  count = local.async_rag ? 1 : 0

  name = "rag-query-documents-dlq-${var.environment}"
  tags = merge(local.common_tags, {
    Name = "rag-query-documents-dlq-${var.environment}"
  })
}

resource "aws_sqs_queue" "rag_query_documents" {
  count = local.async_rag ? 1 : 0

  name                       = "rag-query-documents-${var.environment}"
  visibility_timeout_seconds = 720
  receive_wait_time_seconds  = 0

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.rag_query_documents_dlq[0].arn
    maxReceiveCount     = 3
  })

  tags = merge(local.common_tags, {
    Name = "rag-query-documents-${var.environment}"
  })
}

module "lambda_query_dispatcher" {
  count  = local.async_rag ? 1 : 0
  source = "./modules/lambda"

  function_name          = "rag_lmbd_query_dispatcher-${var.environment}"
  description            = "Encola consultas async RAG y expone estado/resultado (API GW)"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 29
  memory_size            = 256
  ephemeral_storage_size = 512

  source_path = "${path.module}/../apps/rag_lmbd_query_dispatcher"
  environment = var.environment

  environment_variables = {
    RESULT_TABLE_NAME = aws_dynamodb_table.rag_result_query_table[0].name
    QUEUE_URL         = aws_sqs_queue.rag_query_documents[0].url
  }

  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:ConditionCheckItem",
        "dynamodb:Query",
      ]
      resources = [
        aws_dynamodb_table.rag_result_query_table[0].arn,
        "${aws_dynamodb_table.rag_result_query_table[0].arn}/index/*",
      ]
    },
    {
      effect = "Allow"
      actions = [
        "sqs:SendMessage",
        "sqs:GetQueueAttributes",
      ]
      resources = [
        aws_sqs_queue.rag_query_documents[0].arn,
      ]
    },
  ]

  tags = local.common_tags
}
