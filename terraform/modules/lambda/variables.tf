variable "function_name" {
  description = "Name of the Lambda function"
  type        = string
}

variable "description" {
  description = "Description of the Lambda function"
  type        = string
  default     = ""
}

variable "handler" {
  description = "Lambda handler (e.g., index.handler)"
  type        = string
  default     = "index.handler"
}

variable "runtime" {
  description = "Lambda runtime"
  type        = string
  default     = "python3.12"
}

variable "timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 300
}

variable "memory_size" {
  description = "Lambda memory size in MB"
  type        = number
  default     = 512
}

variable "environment_variables" {
  description = "Environment variables for the Lambda"
  type        = map(string)
  default     = {}
}

variable "source_path" {
  description = "Path to the Lambda source code directory"
  type        = string
}

variable "layers" {
  description = "List of Lambda layer ARNs"
  type        = list(string)
  default     = []
}

# VPC Configuration
variable "vpc_id" {
  description = "VPC ID for Lambda"
  type        = string
  default     = null
}

variable "subnet_ids" {
  description = "Subnet IDs for Lambda VPC configuration"
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security group IDs for Lambda"
  type        = list(string)
  default     = []
}

# IAM
variable "attach_policy_statements" {
  description = "Additional IAM policy statements"
  type = list(object({
    effect    = string
    actions   = list(string)
    resources = list(string)
  }))
  default = []
}

# S3 Trigger
variable "s3_trigger_enabled" {
  description = "Enable S3 trigger for Lambda"
  type        = bool
  default     = false
}

variable "use_s3_deployment" {
  description = "Whether to use S3 for Lambda deployment package (required for packages > 50MB)"
  type        = bool
  default     = false
}

variable "s3_bucket_name" {
  description = "S3 bucket name for storing Lambda deployment packages (for large packages > 50MB) and/or S3 trigger"
  type        = string
  default     = ""
}

variable "s3_bucket_arn" {
  description = "S3 bucket ARN for trigger"
  type        = string
  default     = ""
}

variable "s3_events" {
  description = "S3 events to trigger Lambda"
  type        = list(string)
  default     = ["s3:ObjectCreated:*"]
}

variable "s3_filter_prefix" {
  description = "S3 key prefix filter"
  type        = string
  default     = ""
}

variable "s3_filter_suffix" {
  description = "S3 key suffix filter"
  type        = string
  default     = ".pdf"
}

# SQS trigger (optional)
variable "sqs_trigger_enabled" {
  description = "Enable SQS event source mapping for Lambda"
  type        = bool
  default     = false
}

variable "sqs_queue_arn" {
  description = "SQS queue ARN to trigger the Lambda"
  type        = string
  default     = ""
}

variable "sqs_batch_size" {
  description = "Max messages per Lambda invocation from SQS"
  type        = number
  default     = 10
}

variable "sqs_maximum_concurrency" {
  description = "Optional max concurrent Lambda executions per SQS event source (null = AWS default)"
  type        = number
  default     = null
}

variable "sqs_report_batch_item_failures" {
  description = "Si true, el mapping SQS usa ReportBatchItemFailures (el handler debe devolver batchItemFailures)."
  type        = bool
  default     = false
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "reserved_concurrent_executions" {
  description = "Reserved concurrent executions"
  type        = number
  default     = -1
}

variable "ephemeral_storage_size" {
  description = "Ephemeral storage size in MB (512-10240)"
  type        = number
  default     = 512
}

# Copiar como paquete top-level `shared` (p. ej. src/shared) junto a los .py de la Lambda.
variable "shared_package_path" {
  type        = string
  default     = ""
  description = "Ruta del directorio a empaquetar como shared/ (vacío = no copiar)"
}
