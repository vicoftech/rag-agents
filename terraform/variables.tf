# ==============================================================================
# General Configuration
# ==============================================================================

variable "environment" {
  description = "Deployment environment (e.g., dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI named profile to use for credentials"
  type        = string
}

# ==============================================================================
# Network Configuration
# ==============================================================================

variable "vpc_id" {
  description = "VPC ID for resources"
  type        = string
}

variable "subnets" {
  description = "Subnet IDs for Lambda and Aurora"
  type        = list(string)
}

# ==============================================================================
# Aurora PostgreSQL Configuration
# ==============================================================================

variable "master_username" {
  description = "Master username for Aurora"
  type        = string
}

variable "master_password" {
  description = "Master password for Aurora"
  type        = string
  sensitive   = true
}

variable "engine_version" {
  description = "Aurora PostgreSQL engine version"
  type        = string
  default     = "14.11"
}

variable "aurora_min_capacity" {
  description = "Aurora Serverless minimum capacity (ACUs)"
  type        = number
  default     = 0.5
}

variable "aurora_max_capacity" {
  description = "Aurora Serverless maximum capacity (ACUs)"
  type        = number
  default     = 4
}

# ==============================================================================
# S3 Configuration
# ==============================================================================

variable "enable_s3_cors" {
  description = "Enable CORS for S3 bucket"
  type        = bool
  default     = false
}

variable "cors_allowed_origins" {
  description = "Allowed origins for CORS"
  type        = list(string)
  default     = ["*"]
}

# ==============================================================================
# Lambda Configuration
# ==============================================================================

variable "lambda_embeddings_env_vars" {
  description = "Environment variables for the embeddings Lambda"
  type        = map(string)
  default     = {}
}

variable "lambda_query_env_vars" {
  description = "Environment variables for the query Lambda"
  type        = map(string)
  default     = {}
}

variable "lambda_embeddings_config" {
  description = "Configuration for embeddings Lambda"
  type = object({
    timeout                = optional(number, 900)
    memory_size            = optional(number, 1024)
    ephemeral_storage_size = optional(number, 1024)
  })
  default = {}
}

variable "lambda_query_config" {
  description = "Configuration for query Lambda"
  type = object({
    timeout                = optional(number, 120)
    memory_size            = optional(number, 512)
    ephemeral_storage_size = optional(number, 512)
  })
  default = {}
}

# ==============================================================================
# Bedrock Agent Configuration
# ==============================================================================

variable "agent_name" {
  description = "Name of the Bedrock Agent"
  type        = string
  default     = "rag-agent"
}

variable "agent_model_id" {
  description = "Bedrock model ID for the agent"
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "agent_environment_variables" {
  description = "Additional environment variables for the agent Lambda"
  type        = map(string)
  default     = {}
}

# ==============================================================================
# API Gateway & Cognito Configuration
# ==============================================================================

variable "create_cognito_user_pool" {
  description = "Whether to create a new Cognito User Pool for JWT authentication"
  type        = bool
  default     = true
}

variable "cognito_user_pool_id" {
  description = "Existing Cognito User Pool ID (if not creating new one)"
  type        = string
  default     = ""
}

variable "cognito_user_pool_client_id" {
  description = "Existing Cognito User Pool Client ID (if not creating new one)"
  type        = string
  default     = ""
}

variable "cognito_user_pool_arn" {
  description = "Existing Cognito User Pool ARN (if not creating new one)"
  type        = string
  default     = ""
}