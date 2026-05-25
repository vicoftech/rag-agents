# ECS one-shot / manual: rekey PDFs ANMAT (imagen rag-batch-anmat-s3-rekey-prod).

variable "anmat_s3_rekey_image_tag" {
  type        = string
  description = "Tag ECR para batch/anmat-s3-rekey (CI → latest)."
  default     = "latest"
}

variable "anmat_s3_rekey_db_secret_arn" {
  type        = string
  description = "Secrets Manager (postgres) para lookup disposicion."
  default     = "arn:aws:secretsmanager:us-east-1:913123310997:secret:rag-agents/prod/postgres-qN7JTU"
}

variable "anmat_s3_rekey_manifest_s3_uri" {
  type        = string
  description = "Manifiesto de PDFs a rekey (subir a manifests/ antes del run)."
  default     = "s3://rag-documents-prod-913123310997/manifests/tenant_anmat_s3_not_in_documents_202605212328.json"
}

variable "anmat_s3_rekey_task_cpu" {
  type    = number
  default = 2048
}

variable "anmat_s3_rekey_task_memory" {
  type    = number
  default = 4096
}

locals {
  anmat_s3_rekey_family = "${var.project_name}-anmat-s3-rekey-${var.environment}"
  anmat_s3_rekey_image  = "${aws_ecr_repository.anmat_s3_rekey.repository_url}:${var.anmat_s3_rekey_image_tag}"
}

resource "aws_iam_role_policy" "ecs_task_anmat_s3_rekey" {
  name = "anmat-s3-rekey"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsPostgres"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = [var.anmat_s3_rekey_db_secret_arn]
      },
      {
        Sid    = "S3DocumentsRekey"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:HeadObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_documents_bucket}",
          "arn:aws:s3:::${var.s3_documents_bucket}/*"
        ]
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "anmat_s3_rekey" {
  name              = "/ecs/${local.anmat_s3_rekey_family}"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_task_definition" "anmat_s3_rekey" {
  family                   = local.anmat_s3_rekey_family
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.anmat_s3_rekey_task_cpu
  memory                   = var.anmat_s3_rekey_task_memory
  execution_role_arn       = aws_iam_role.ecs_exec.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "rekey"
      image     = local.anmat_s3_rekey_image
      essential = true
      user      = "1000"
      environment = [
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "S3_DOCUMENTS_BUCKET", value = var.s3_documents_bucket },
        { name = "MANIFEST_S3_URI", value = var.anmat_s3_rekey_manifest_s3_uri },
        { name = "DB_SECRET_ARN", value = var.anmat_s3_rekey_db_secret_arn },
        { name = "DISPERSION_DATE_FIELD", value = "fechayhora_revision" },
        { name = "REKEY_LOG_S3_PREFIX", value = "manifests/rekey-runs/" },
        { name = "REKEY_RESUME_OK_S3_PREFIX", value = "manifests/rekey-runs/" },
        { name = "REKEY_RESUME", value = "1" },
        { name = "DRY_RUN", value = var.anmat_s3_rekey_dry_run ? "1" : "0" },
        { name = "DELETE_SOURCE", value = var.anmat_s3_rekey_delete_source ? "1" : "0" },
        { name = "MAX_ITEMS", value = tostring(var.anmat_s3_rekey_max_items) },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.anmat_s3_rekey.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "rekey"
        }
      }
    }
  ])
}

variable "anmat_s3_rekey_dry_run" {
  type        = bool
  description = "1 en task env: no copia S3 (prueba)."
  default     = false
}

variable "anmat_s3_rekey_delete_source" {
  type    = bool
  default = false
}

variable "anmat_s3_rekey_max_items" {
  type        = number
  description = "0 = todos los ítems del manifiesto."
  default     = 0
}

output "anmat_s3_rekey_task_definition_family" {
  value = aws_ecs_task_definition.anmat_s3_rekey.family
}

output "anmat_s3_rekey_log_group" {
  value = aws_cloudwatch_log_group.anmat_s3_rekey.name
}
