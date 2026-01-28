# ==============================================================================
# General Variables
# ==============================================================================

variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

# ==============================================================================
# Runtime Variables
# ==============================================================================

variable "create_runtime" {
  description = "Whether to create the AgentCore Runtime"
  type        = bool
  default     = true
}

variable "runtime_container_uri" {
  description = "ECR URI of the container image for the runtime"
  type        = string
}

variable "runtime_description" {
  description = "Description of the AgentCore Runtime"
  type        = string
  default     = "Bedrock AgentCore Runtime"
}

variable "runtime_role_arn" {
  description = "Optional external IAM role ARN for the runtime. If null, one will be created"
  type        = string
  default     = null
}

variable "runtime_network_mode" {
  description = "Network mode for the runtime (PUBLIC or VPC)"
  type        = string
  default     = "PUBLIC"
  
  validation {
    condition     = contains(["PUBLIC", "VPC"], var.runtime_network_mode)
    error_message = "runtime_network_mode must be PUBLIC or VPC"
  }
}

variable "runtime_subnet_ids" {
  description = "Subnet IDs for VPC network mode"
  type        = list(string)
  default     = []
}

variable "runtime_security_group_ids" {
  description = "Security group IDs for VPC network mode"
  type        = list(string)
  default     = []
}

variable "runtime_protocol" {
  description = "Server protocol for the runtime (HTTP, MCP, A2A)"
  type        = string
  default     = "HTTP"
  
  validation {
    condition     = contains(["HTTP", "MCP", "A2A"], var.runtime_protocol)
    error_message = "runtime_protocol must be HTTP, MCP, or A2A"
  }
}

variable "runtime_environment_variables" {
  description = "Environment variables for the runtime container"
  type        = map(string)
  default     = {}
}

variable "runtime_idle_timeout" {
  description = "Idle session timeout in seconds"
  type        = number
  default     = 3600
}

variable "runtime_max_lifetime" {
  description = "Maximum lifetime in seconds (max 28800 = 8 hours)"
  type        = number
  default     = 28800
  
  validation {
    condition     = var.runtime_max_lifetime <= 28800
    error_message = "runtime_max_lifetime cannot exceed 28800 seconds (8 hours)"
  }
}

variable "lambda_function_arns" {
  description = "List of Lambda function ARNs that the runtime can invoke"
  type        = list(string)
  default     = ["*"]
}

# ==============================================================================
# Runtime Endpoint Variables
# ==============================================================================

variable "create_runtime_endpoint" {
  description = "Whether to create the AgentCore Runtime Endpoint"
  type        = bool
  default     = true
}

# ==============================================================================
# Cognito Variables
# ==============================================================================

variable "create_cognito" {
  description = "Whether to create a Cognito User Pool for JWT authentication"
  type        = bool
  default     = true
}

variable "cognito_user_pool_id" {
  description = "Existing Cognito User Pool ID (if not creating new)"
  type        = string
  default     = null
}

variable "cognito_client_id" {
  description = "Existing Cognito Client ID (if not creating new)"
  type        = string
  default     = null
}

variable "cognito_discovery_url" {
  description = "Existing OIDC discovery URL (if not creating Cognito)"
  type        = string
  default     = null
}

variable "cognito_allowed_audience" {
  description = "Allowed audience values for JWT validation"
  type        = list(string)
  default     = []
}

variable "cognito_password_policy" {
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

variable "cognito_mfa_configuration" {
  description = "MFA configuration (OFF, OPTIONAL, REQUIRED)"
  type        = string
  default     = "OFF"
}

variable "cognito_callback_urls" {
  description = "Callback URLs for Cognito"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "cognito_logout_urls" {
  description = "Logout URLs for Cognito"
  type        = list(string)
  default     = ["http://localhost:3000"]
}

variable "cognito_token_validity_hours" {
  description = "Token validity in hours"
  type        = number
  default     = 24
}

variable "cognito_refresh_token_validity_days" {
  description = "Refresh token validity in days"
  type        = number
  default     = 30
}

# ==============================================================================
# Memory Variables
# ==============================================================================

variable "create_memory" {
  description = "Whether to create AgentCore Memory"
  type        = bool
  default     = true
}

variable "memory_description" {
  description = "Description of the memory"
  type        = string
  default     = "AgentCore Memory for conversation context"
}

variable "memory_role_arn" {
  description = "Optional external IAM role ARN for memory. If null, one will be created"
  type        = string
  default     = null
}

variable "memory_event_expiry_days" {
  description = "Days until memory events expire"
  type        = number
  default     = 90
}

variable "memory_kms_key_arn" {
  description = "KMS key ARN for memory encryption"
  type        = string
  default     = null
}

# Memory Strategies
variable "memory_enable_semantic" {
  description = "Enable semantic memory strategy (extracts factual knowledge)"
  type        = bool
  default     = true
}

variable "memory_semantic_namespaces" {
  description = "Namespaces for semantic memory"
  type        = list(string)
  default     = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
}

variable "memory_enable_summary" {
  description = "Enable summary memory strategy (preserves conversation context)"
  type        = bool
  default     = true
}

variable "memory_summary_namespaces" {
  description = "Namespaces for summary memory"
  type        = list(string)
  default     = ["/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"]
}

variable "memory_enable_user_preference" {
  description = "Enable user preference memory strategy (personalization)"
  type        = bool
  default     = true
}

variable "memory_user_preference_namespaces" {
  description = "Namespaces for user preference memory"
  type        = list(string)
  default     = ["/strategies/{memoryStrategyId}/actors/{actorId}"]
}

variable "memory_custom_strategy" {
  description = "Custom memory strategy configuration"
  type = object({
    name        = string
    description = optional(string)
    namespaces  = list(string)
    configuration = optional(object({
      semantic_override = optional(object({
        extraction = optional(object({
          append_to_prompt = optional(string)
          model_id         = optional(string)
        }))
        consolidation = optional(object({
          append_to_prompt = optional(string)
          model_id         = optional(string)
        }))
      }))
      summary_override = optional(object({
        consolidation = optional(object({
          append_to_prompt = optional(string)
          model_id         = optional(string)
        }))
      }))
      user_preference_override = optional(object({
        extraction = optional(object({
          append_to_prompt = optional(string)
          model_id         = optional(string)
        }))
        consolidation = optional(object({
          append_to_prompt = optional(string)
          model_id         = optional(string)
        }))
      }))
    }))
  })
  default = null
}

# ==============================================================================
# Gateway Variables
# ==============================================================================

variable "create_gateway" {
  description = "Whether to create AgentCore Gateway"
  type        = bool
  default     = true
}

variable "gateway_description" {
  description = "Description of the gateway"
  type        = string
  default     = "AgentCore Gateway for REST API access"
}

variable "gateway_role_arn" {
  description = "Optional external IAM role ARN for gateway. If null, one will be created"
  type        = string
  default     = null
}

variable "gateway_instructions" {
  description = "Instructions for MCP protocol"
  type        = string
  default     = "Gateway for accessing agent tools and resources"
}

variable "gateway_search_type" {
  description = "Search type for MCP (DEFAULT, SEMANTIC)"
  type        = string
  default     = "DEFAULT"
}

variable "gateway_mcp_versions" {
  description = "Supported MCP versions (use date format: 2025-11-25, 2025-03-26, 2025-06-18)"
  type        = list(string)
  default     = ["2025-11-25"]
}

variable "gateway_kms_key_arn" {
  description = "KMS key ARN for gateway encryption"
  type        = string
  default     = null
}

variable "gateway_exception_level" {
  description = "Exception level (PARTIAL, FULL, DEBUG)"
  type        = string
  default     = "DEBUG"
}

# ==============================================================================
# Gateway Target Variables
# ==============================================================================

variable "create_gateway_target" {
  description = "Whether to create a Gateway Target"
  type        = bool
  default     = true
}

variable "gateway_target_lambda_arn" {
  description = "Lambda ARN for the gateway target"
  type        = string
  default     = null
}

variable "gateway_target_tool_name" {
  description = "Name of the tool exposed by the gateway"
  type        = string
  default     = "knowledge_base_search"
}

variable "gateway_target_tool_description" {
  description = "Description of the tool"
  type        = string
  default     = "Search the knowledge base for relevant information"
}

variable "gateway_target_tool_input_description" {
  description = "Description of the tool input schema"
  type        = string
  default     = "Input parameters for knowledge base search"
}

variable "gateway_target_tool_input_properties" {
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
