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

variable "aws_region" {
  description = "AWS region to deploy resources (used by providers)"
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

variable "existing_rag_lambda_security_group_id" {
  description = "Si no vacío, no se crea aws_security_group.rag_lambda: se reutiliza este SG (prod con Lambdas ya desplegadas)."
  type        = string
  default     = ""
}

variable "boletin_oficial_state_machine_name_override" {
  description = "Si no vacío, usa este nombre para el Step Functions de bolinks→s3writer→dbwriter (p. ej. prod heredado sin sufijo -async)."
  type        = string
  default     = ""
}

variable "create_vpc_endpoint_s3" {
  description = "Crear VPC endpoint Gateway para S3 (desactivar si la VPC ya tiene ruta/prefix list a S3)"
  type        = bool
  default     = true
}

variable "create_vpc_endpoint_bedrock" {
  description = "Crear VPC endpoint Interface para bedrock-runtime (desactivar si ya existe uno con private DNS en la VPC)"
  type        = bool
  default     = true
}

variable "create_vpc_endpoint_secrets_textract" {
  description = "Interface VPCE para Secrets Manager y Textract. En subredes privadas sin NAT, sin esto las llamadas HTTPS a esas APIs cuelgan hasta timeout (S3 va por Gateway; Bedrock suele tener VPCE aparte)."
  type        = bool
  default     = false
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
  default     = ""
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

variable "create_aurora_cluster" {
  description = "Whether to create Aurora cluster resources"
  type        = bool
  default     = true
}

variable "existing_db_host" {
  description = "Existing PostgreSQL writer endpoint (used when create_aurora_cluster=false)"
  type        = string
  default     = ""
}

variable "existing_db_name" {
  description = "Existing PostgreSQL database name (used when create_aurora_cluster=false)"
  type        = string
  default     = "postgres"
}

variable "existing_db_port" {
  description = "Existing PostgreSQL port (used when create_aurora_cluster=false)"
  type        = number
  default     = 5432
}

variable "existing_db_security_group_id" {
  description = "Security group ID of existing PostgreSQL cluster (used when create_aurora_cluster=false)"
  type        = string
  default     = ""
}

variable "db_secret_id" {
  description = "Secrets Manager secret ID/ARN with DB credentials (username/password)"
  type        = string
  default     = ""
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

variable "s3_bucket_force_destroy" {
  description = "Si true, el bucket de documentos se puede borrar con objetos (usar solo para terraform destroy / reset)"
  type        = bool
  default     = false
}

variable "create_documents_bucket" {
  description = "Si false, no crea el bucket: usa data.aws_s3_bucket sobre rag-documents-<environment>-<account_id> (debe existir, p. ej. prod ya creado)."
  type        = bool
  default     = true
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

variable "lambda_obtener_alertas_env_vars" {
  description = "Environment variables for the obtener_alertas Lambda (external DB/project)"
  type        = map(string)
  default     = {}
}

variable "lambda_obtener_alertas_db" {
  description = "External DB config for rag_lmbd_obtener_alertas (agnostic, per environment tfvars)"
  type = object({
    host     = string
    port     = number
    user     = string
    password = string
    database = string
    sslmode  = optional(string, "require")
  })
  default = {
    host     = ""
    port     = 5432
    user     = ""
    password = ""
    database = ""
    sslmode  = "require"
  }
  sensitive = true
}

variable "lambda_obtener_alertas_security_group_ids" {
  description = "Security groups for rag_lmbd_obtener_alertas Lambda ENI(s). Must allow connectivity to target PostgreSQL."
  type        = list(string)
  default     = []
}

variable "lambda_embeddings_config" {
  description = "Configuration for embeddings Lambda"
  type = object({
    timeout                = number
    memory_size            = number
    ephemeral_storage_size = number
  })
  default = {
    timeout                = 30
    memory_size            = 1024
    ephemeral_storage_size = 1024
  }
}

variable "lambda_embeddings_sqs_concurrency" {
  description = "Límite de concurrencia del evento SQS → Lambda embeddings (más = más PDFs en paralelo; coordinar con Bedrock/Textract/Aurora)"
  type        = number
  default     = 30
}

variable "lambda_embeddings_reserved_concurrency" {
  description = "Reserved concurrent executions de la Lambda embeddings (debe ser >= lambda_embeddings_sqs_concurrency; -1 = sin reserva = cuenta límite de región)"
  type        = number
  default     = 30
}

variable "lambda_query_config" {
  description = "Configuration for query Lambda"
  type = object({
    timeout                = number
    memory_size            = number
    ephemeral_storage_size = number
  })
  default = {
    timeout                = 120
    memory_size            = 512
    ephemeral_storage_size = 512
  }
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
    minimum_length    = number
    require_lowercase = bool
    require_uppercase = bool
    require_numbers   = bool
    require_symbols   = bool
  })
  default = {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
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
    name          = string
    description   = string
    namespaces    = list(string)
    configuration = any
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

# Boletín Oficial Configuration
variable "notification_email" {
  description = "Email address for pipeline notifications"
  type        = string
  default     = ""
}

variable "boletin_base_url" {
  description = "Base URL for Boletín Oficial website"
  type        = string
  default     = "https://www.boletinoficial.gob.ar"
}

variable "boletin_default_section" {
  description = "Default section to fetch (primera, segunda, tercera, cuarta)"
  type        = string
  default     = "primera"
}

variable "boletin_request_timeout" {
  description = "Timeout for HTTP requests to Boletín Oficial (seconds)"
  type        = number
  default     = 30
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
    required    = bool
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

variable "sparticuz_chromium_layer_zip_url" {
  description = "Official Sparticuz Chromium Lambda layer (x86_64) ZIP URL for rag_lmbd_anmatlinks"
  type        = string
  default     = "https://github.com/Sparticuz/chromium/releases/download/v143.0.4/chromium-v143.0.4-layer.x64.zip"
}

variable "create_rag_ingestion" {
  description = "Desplegar pipeline RAG v2: DDB, SQS, Lambdas, Step Functions, regla S3 (EventBridge)"
  type        = bool
  default     = false
}

variable "rag_embed_sqs_maximum_concurrency" {
  description = "RAG v2: máximo de invocaciones concurrentes del embed worker (trigger SQS chunk_batches)"
  type        = number
  default     = 5
}

variable "s3_object_created_to_eventbridge" {
  description = "Bucket de documentos: notificar a EventBridge (Object Created). Necesario para SFN RAG o reglas en EB."
  type        = bool
  default     = false
}

variable "legacy_s3_embeddings_enqueue_enabled" {
  description = "Mantener S3 → Lambda encolador → SQS old rag-embeddings-ingest (deshabilitar al usar solo RAG v2)"
  type        = bool
  default     = true
}