# ==============================================================================
# Bedrock Agent Module Variables
# ==============================================================================

variable "function_name" {
  description = "Name of the Lambda function"
  type        = string
}

variable "description" {
  description = "Description of the Lambda function"
  type        = string
  default     = "Bedrock Agent Core handler"
}

variable "handler" {
  description = "Lambda handler"
  type        = string
  default     = "api_gateway_handler.lambda_handler"
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

variable "ephemeral_storage_size" {
  description = "Lambda ephemeral storage size in MB"
  type        = number
  default     = 512
}

variable "source_path" {
  description = "Path to the Lambda source code"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for Lambda (optional)"
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Subnet IDs for Lambda (optional)"
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security group IDs for Lambda (optional)"
  type        = list(string)
  default     = []
}

variable "environment_variables" {
  description = "Environment variables for Lambda"
  type        = map(string)
  default     = {}
}

variable "agent_name" {
  description = "Name of the Bedrock Agent"
  type        = string
}

variable "agent_description" {
  description = "Description of the Bedrock Agent"
  type        = string
  default     = "RAG Agent deployed via Bedrock Agent Core"
}

variable "agent_model_id" {
  description = "Bedrock model ID for the agent"
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "lambda_query_function_name" {
  description = "Name of the RAG query Lambda function (for permissions)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

