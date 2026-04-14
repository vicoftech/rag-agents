variable "state_machine_name" {
  description = "Name of the Step Functions state machine"
  type        = string
}

variable "anmat_function_arn" {
  description = "ARN of rag_lmbd_anmatlinks Lambda"
  type        = string
}

variable "anmat_function_name" {
  description = "Name of rag_lmbd_anmatlinks (for lambda_permission)"
  type        = string
}

variable "alert_queue_url" {
  description = "SQS queue URL for rag_lmbd_s3writer (alert-s3writer-*)"
  type        = string
}

variable "alert_queue_arn" {
  description = "SQS queue ARN (for IAM policy)"
  type        = string
}

variable "tags" {
  description = "Tags for IAM and state machine"
  type        = map(string)
  default     = {}
}

variable "map_max_concurrency" {
  description = "Max parallel SQS SendMessage branches in the Map state"
  type        = number
  default     = 20
}
