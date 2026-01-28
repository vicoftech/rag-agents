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
  description = "AWS CLI named profile to use for credentials (optional, leave empty or set to \"\" to use default credentials from environment or ~/.aws/credentials)"
  type        = string
  default     = ""
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

# ==============================================================================
# Bedrock AgentCore Configuration
# ==============================================================================

variable "create_agentcore" {
  description = "Whether to create the AgentCore module"
  type        = bool
  default     = false
}

variable "agentcore_name_prefix" {
  description = "Prefix for AgentCore resource names"
  type        = string
  default     = "rag_agent"
}

# Runtime Configuration
variable "agentcore_create_runtime" {
  description = "Whether to create the AgentCore Runtime"
  type        = bool
  default     = true
}

variable "agentcore_runtime_container_uri" {
  description = "ECR URI of the container image for the runtime"
  type        = string
  default     = ""
}

variable "agentcore_runtime_description" {
  description = "Description of the AgentCore Runtime"
  type        = string
  default     = "RAG Agent Runtime with Strands"
}

variable "agentcore_runtime_network_mode" {
  description = "Network mode for the runtime (PUBLIC or VPC)"
  type        = string
  default     = "PUBLIC"
}

variable "agentcore_runtime_protocol" {
  description = "Server protocol for the runtime (HTTP, MCP, A2A)"
  type        = string
  default     = "HTTP"
}

variable "agentcore_runtime_idle_timeout" {
  description = "Idle session timeout in seconds"
  type        = number
  default     = 3600
}

variable "agentcore_runtime_max_lifetime" {
  description = "Maximum lifetime in seconds (max 28800 = 8 hours)"
  type        = number
  default     = 28800
}

variable "agentcore_runtime_environment_variables" {
  description = "Additional environment variables for the runtime"
  type        = map(string)
  default     = {}
}

# Runtime Endpoint
variable "agentcore_create_runtime_endpoint" {
  description = "Whether to create the AgentCore Runtime Endpoint"
  type        = bool
  default     = true
}

# Cognito Configuration
variable "agentcore_create_cognito" {
  description = "Whether to create a Cognito User Pool for authentication"
  type        = bool
  default     = true
}

variable "agentcore_cognito_user_pool_id" {
  description = "Existing Cognito User Pool ID"
  type        = string
  default     = null
}

variable "agentcore_cognito_client_id" {
  description = "Existing Cognito Client ID"
  type        = string
  default     = null
}

variable "agentcore_cognito_discovery_url" {
  description = "Existing OIDC discovery URL"
  type        = string
  default     = null
}

variable "agentcore_cognito_allowed_audience" {
  description = "Allowed audience values for JWT validation"
  type        = list(string)
  default     = []
}

variable "agentcore_cognito_password_policy" {
  description = "Password policy for Cognito User Pool"
  type = object({
    minimum_length    = optional(number, 8)
    require_lowercase = optional(bool, true)
    require_uppercase = optional(bool, true)
    require_numbers   = optional(bool, true)
    require_symbols   = optional(bool, true)
  })
  default = {}
}

variable "agentcore_cognito_mfa_configuration" {
  description = "MFA configuration (OFF, OPTIONAL, REQUIRED)"
  type        = string
  default     = "OFF"
}

variable "agentcore_cognito_callback_urls" {
  description = "Callback URLs for Cognito"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "agentcore_cognito_logout_urls" {
  description = "Logout URLs for Cognito"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "agentcore_cognito_token_validity_hours" {
  description = "Token validity in hours"
  type        = number
  default     = 24
}

variable "agentcore_cognito_refresh_token_validity_days" {
  description = "Refresh token validity in days"
  type        = number
  default     = 30
}

# Memory Configuration
variable "agentcore_create_memory" {
  description = "Whether to create AgentCore Memory"
  type        = bool
  default     = true
}

variable "agentcore_memory_description" {
  description = "Description of the memory"
  type        = string
  default     = "Memory for conversation context and user preferences"
}

variable "agentcore_memory_event_expiry_days" {
  description = "Days until memory events expire"
  type        = number
  default     = 90
}

variable "agentcore_memory_kms_key_arn" {
  description = "KMS key ARN for memory encryption"
  type        = string
  default     = null
}

variable "agentcore_memory_enable_semantic" {
  description = "Enable semantic memory strategy (extracts factual knowledge)"
  type        = bool
  default     = true
}

variable "agentcore_memory_semantic_namespaces" {
  description = "Namespaces for semantic memory"
  type        = list(string)
  default     = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
}

variable "agentcore_memory_enable_summary" {
  description = "Enable summary memory strategy (preserves conversation context)"
  type        = bool
  default     = true
}

variable "agentcore_memory_summary_namespaces" {
  description = "Namespaces for summary memory"
  type        = list(string)
  default     = ["/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"]
}

variable "agentcore_memory_enable_user_preference" {
  description = "Enable user preference memory strategy (personalization)"
  type        = bool
  default     = true
}

variable "agentcore_memory_user_preference_namespaces" {
  description = "Namespaces for user preference memory"
  type        = list(string)
  default     = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
}

variable "agentcore_memory_custom_strategy" {
  description = "Custom memory strategy configuration"
  type = object({
    name        = string
    description = optional(string)
    namespaces  = list(string)
    configuration = optional(any)
  })
  default = null
}

# Gateway Configuration
variable "agentcore_create_gateway" {
  description = "Whether to create AgentCore Gateway"
  type        = bool
  default     = true
}

variable "agentcore_gateway_description" {
  description = "Description of the gateway"
  type        = string
  default     = "REST API Gateway for RAG Agent"
}

variable "agentcore_gateway_instructions" {
  description = "Instructions for MCP protocol"
  type        = string
  default     = "Gateway for accessing RAG agent tools and knowledge base"
}

variable "agentcore_gateway_search_type" {
  description = "Search type for MCP (DEFAULT, SEMANTIC)"
  type        = string
  default     = "SEMANTIC"
}

variable "agentcore_gateway_mcp_versions" {
  description = "Supported MCP versions (use date format: 2025-11-25, 2025-03-26, 2025-06-18)"
  type        = list(string)
  default     = ["2025-11-25"]
}

variable "agentcore_gateway_kms_key_arn" {
  description = "KMS key ARN for gateway encryption"
  type        = string
  default     = null
}

variable "agentcore_gateway_exception_level" {
  description = "Exception level (PARTIAL, FULL, DEBUG)"
  type        = string
  default     = "DEBUG"
}

# Gateway Target Configuration
variable "agentcore_create_gateway_target" {
  description = "Whether to create a Gateway Target"
  type        = bool
  default     = true
}

variable "agentcore_gateway_target_tool_name" {
  description = "Name of the tool exposed by the gateway"
  type        = string
  default     = "knowledge_base_search"
}

variable "agentcore_gateway_target_tool_description" {
  description = "Description of the tool"
  type        = string
  default     = "Search the knowledge base for relevant information using semantic search"
}

variable "agentcore_gateway_target_tool_input_description" {
  description = "Description of the tool input schema"
  type        = string
  default     = "Input parameters for knowledge base search"
}

variable "agentcore_gateway_target_tool_input_properties" {
  description = "Input properties for the gateway target tool"
  type = list(object({
    name        = string
    type        = string
    description = string
    required    = optional(bool, false)
  }))
  default = [
    {
      name        = "query"
      type        = "string"
      description = "The search query"
      required    = true
    },
    {
      name        = "tenant_id"
      type        = "string"
      description = "Tenant identifier"
      required    = true
    },
    {
      name        = "agent_id"
      type        = "string"
      description = "Agent identifier"
      required    = true
    }
  ]
}