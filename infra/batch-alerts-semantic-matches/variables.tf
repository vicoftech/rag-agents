variable "aws_region" {
  type        = string
  description = "Región AWS (debe coincidir con Lambdas y colas)."
  default     = "us-east-1"
}

variable "aws_profile" {
  type        = string
  description = "Perfil ~/.aws para la cuenta correcta (p. ej. asap_main para 913123310997)."
  default     = "asap_main"
}

variable "project_name" {
  type        = string
  description = "Prefijo de nombres de recursos."
  default     = "rag-batch-alerts"
}

variable "environment" {
  type        = string
  description = "Sufijo de entorno (prod, qa, ...)."
  default     = "prod"
}

variable "vpc_id" {
  type        = string
  description = "VPC donde corren las tareas Fargate (misma que Lambdas con salida a internet vía NAT recomendado)."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Subredes para awsvpc (privadas con NAT o públicas con assign_public_ip)."
}

variable "assign_public_ip" {
  type        = bool
  description = "ENABLED si las subnets son públicas y no hay NAT."
  default     = false
}

variable "s3_documents_bucket" {
  type        = string
  description = "Bucket del argumento --s3-bucket del script."
  default     = "rag-documents-prod-913123310997"
}

variable "lambda_env_suffix" {
  type        = string
  description = "Sufijo en nombres de Lambda (p. ej. prod → rag_lmbd_query-prod)."
  default     = "prod"
}

variable "sqs_env_suffix" {
  type        = string
  description = "Sufijo en nombres de colas SQS (p. ej. prod)."
  default     = "prod"
}

variable "schedule_cron_anmat" {
  type        = string
  description = "Cron UTC EventBridge Scheduler, solo lun–vie (AL-01). Default: 10:30 ART (UTC-3) → 13:30 UTC."
  default     = "cron(30 13 ? * MON-FRI *)"
}

variable "schedule_cron_boletin" {
  type        = string
  description = "Cron UTC, solo lun–vie (AL-01). Default: 11:00 ART → 14:00 UTC."
  default     = "cron(0 14 ? * MON-FRI *)"
}

variable "batch_parallel_anmat" {
  type        = number
  description = "Argumento --parallel del script para la tarea anmat."
  default     = 2
}

variable "batch_parallel_boletin" {
  type        = number
  description = "Argumento --parallel del script para la tarea boletín."
  default     = 4
}

variable "batch_trace_lambda_payloads" {
  type        = bool
  description = "Si true, el contenedor pasa --trace-lambda-payloads y --output-trace /tmp/<corrida>_lambda_trace.json."
  default     = true
}

variable "batch_include_zero_chunk_anmat" {
  type        = bool
  description = "Si true, tarea anmat añade --include-zero-chunk-resultados."
  default     = false
}

variable "batch_include_zero_chunk_boletin" {
  type        = bool
  description = "Si true, tarea boletín añade --include-zero-chunk-resultados."
  default     = false
}

variable "batch_no_created_at_filter" {
  type        = bool
  description = "Si true, añade --no-created-at-filter (ventana completa). Si false, ventana UTC del script (created_at_span_days)."
  default     = false
}

variable "batch_testing_email" {
  type        = string
  description = "Si no vacío, el contenedor pasa --testing-email (reemplaza destinatarios en JSON/notificaciones). Vacío en prod normal."
  default     = ""
  sensitive   = true
}

variable "task_cpu" {
  type        = number
  description = "Unidades CPU Fargate (1024 = 1 vCPU)."
  default     = 2048
}

variable "task_memory" {
  type        = number
  description = "Memoria MB Fargate."
  default     = 8192
}

variable "image_tag" {
  type        = string
  description = "Tag de imagen en ECR."
  default     = "latest"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "github_repo_full" {
  type        = string
  description = "OWNER/REPO para la condición OIDC repo:OWNER/REPO:* (sin https)."
  default     = "vicoftech/rag-agents"
}
