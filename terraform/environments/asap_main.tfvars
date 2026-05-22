# ==============================================================================
# ASAP Main Environment Configuration
# ==============================================================================

# General
region      = "us-east-1"
aws_region  = "us-east-1"
aws_profile = "asap_main"
environment = "dev"

# Network
vpc_id  = "vpc-0220b63692086a550"
subnets = ["subnet-04cc462043523dcb9", "subnet-0254c9d900c8b2fdc"]

# Aurora PostgreSQL
master_username     = "dev_master"
master_password     = "DevPassword123!"
engine_version      = "14.20"
aurora_min_capacity = 0.5
aurora_max_capacity = 4

# S3
enable_s3_cors       = false
cors_allowed_origins = ["*"]

# ==============================================================================
# Lambda Embeddings Configuration
# ==============================================================================

lambda_embeddings_config = {
  timeout                = 300
  memory_size            = 1024
  ephemeral_storage_size = 1024
}

# Máx. 2 PDFs vía SQS; tope 4 ejecuciones de la función; Bedrock en lotes de 2 chunks.
lambda_embeddings_sqs_concurrency      = 2
lambda_embeddings_reserved_concurrency = 4

lambda_embeddings_env_vars = {
  EMBEDDINGS_MODEL      = "cohere.embed-v4:0"
  EMBED_BATCH_SIZE      = "2"
  # Claves S3 tipo boletin_oficial/YYYYMMDD/.../archivo.pdf (sin /documents/<uuid>/)
  RAG_S3_DEFAULT_AGENT_ID  = "25abefca-8e5c-4c6e-973d-2fad3af8b469"
  RAG_S3_PREFIX_SCHEMA_MAP = "{\"boletin_oficial\":\"tenant_boletin\"}"
  # Agrega más variables de entorno aquí según necesites
  # LOG_LEVEL = "INFO"
  DB_NAME               = "postgres"
  DB_USER               = "dev_master"
  DB_PASSWORD           = "DevPassword123!"
  DB_HOST               = "aurora-pg-dev.cluster-ch7yo6tzxi4l.us-east-1.rds.amazonaws.com"
  DB_PORT               = "5432"
  MAX_EMBED_TEXT_LENGTH = "20000"
}

# ==============================================================================
# Lambda Query Configuration
# ==============================================================================

lambda_query_config = {
  timeout                = 120
  memory_size            = 512
  ephemeral_storage_size = 512
}

lambda_query_env_vars = {
  DB_NAME            = "postgres"
  DB_USER            = "dev_master"
  DB_PASSWORD        = "DevPassword123!"
  DB_HOST            = "aurora-pg-dev.cluster-ch7yo6tzxi4l.us-east-1.rds.amazonaws.com"
  DB_PORT            = "5432"
  MAIN_LLM_MODEL     = "openai.gpt-oss-120b-1:0"
  FALLBACK_LLM_MODEL = "openai.gpt-oss-20b-1:0"
  #EMBEDDINGS_MODEL = "amazon.titan-embed-text-v2:0"
  EMBEDDINGS_MODEL      = "cohere.embed-v4:0"
  OUTPUT_TOKENS         = "2048"
  MAX_EMBED_TEXT_LENGTH = "20000"
}

lambda_obtener_alertas_db = {
  host     = "aurora-pg-dev.cluster-ch7yo6tzxi4l.us-east-1.rds.amazonaws.com"
  port     = 5432
  user     = "dev_master"
  password = "DevPassword123!"
  database = "ragdb_dev"
  sslmode  = "require"
}

# ==============================================================================
# Bedrock AgentCore Configuration
# ==============================================================================

# Habilitar AgentCore
create_agentcore = false

# Prefijo para nombres de recursos
agentcore_name_prefix = "rag_agent"

# ==============================================================================
# Runtime (Container ECR)
# ==============================================================================

agentcore_create_runtime = true

# URI de la imagen ECR - ACTUALIZAR con tu imagen
agentcore_runtime_container_uri = "913123310997.dkr.ecr.us-east-1.amazonaws.com/rag-agent:latest"

agentcore_runtime_description = "RAG Agent Runtime basado en Strands"

# Network mode: PUBLIC o VPC
agentcore_runtime_network_mode = "PUBLIC"

# Protocolo: HTTP, MCP o A2A
agentcore_runtime_protocol = "HTTP"

# Timeouts
agentcore_runtime_idle_timeout = 3600  # 1 hora
agentcore_runtime_max_lifetime = 28800 # 8 horas (máximo permitido)

# Variables de entorno adicionales para el runtime
agentcore_runtime_environment_variables = {
  LOG_LEVEL   = "INFO"
  ENVIRONMENT = "dev"
}

# Crear endpoint REST
agentcore_create_runtime_endpoint = true

# ==============================================================================
# Cognito (Seguridad JWT)
# ==============================================================================

agentcore_create_cognito = true

# Política de contraseñas
agentcore_cognito_password_policy = {
  minimum_length    = 8
  require_lowercase = true
  require_uppercase = true
  require_numbers   = true
  require_symbols   = false
}

# MFA: OFF, OPTIONAL, REQUIRED
agentcore_cognito_mfa_configuration = "OFF"

# URLs de callback/logout
agentcore_cognito_callback_urls = ["http://localhost:3000", "https://localhost:3000"]
agentcore_cognito_logout_urls   = ["http://localhost:3000", "https://localhost:3000"]

# Validez de tokens
agentcore_cognito_token_validity_hours        = 24
agentcore_cognito_refresh_token_validity_days = 30

# ==============================================================================
# Memory (Corto y Largo Plazo)
# ==============================================================================

agentcore_create_memory = true

agentcore_memory_description = "Memoria para contexto conversacional y preferencias de usuario"

# Días hasta que expiran los eventos de memoria
agentcore_memory_event_expiry_days = 90

# Estrategia Semántica (Largo plazo - conocimiento factual)
# NOTA: Solo se puede habilitar UNA estrategia a la vez por limitación del API
agentcore_memory_enable_semantic = true
agentcore_memory_semantic_namespaces = [
  "/rag_agent/semantic/actors/{actorId}"
]

# Estrategia de Resumen (Corto plazo - contexto de conversación)
# Deshabilitado temporalmente - habilitar después de crear el recurso
agentcore_memory_enable_summary = false
agentcore_memory_summary_namespaces = [
  "/rag_agent/summary/actors/{actorId}/sessions/{sessionId}"
]

# Estrategia de Preferencias de Usuario (Largo plazo - personalización)
# Deshabilitado temporalmente - habilitar después de crear el recurso
agentcore_memory_enable_user_preference = false
agentcore_memory_user_preference_namespaces = [
  "/rag_agent/preferences/actors/{actorId}"
]

# ==============================================================================
# Gateway (API REST)
# ==============================================================================

agentcore_create_gateway = true

agentcore_gateway_description = "Gateway REST para acceso al RAG Agent"

agentcore_gateway_instructions = "Gateway para acceder a herramientas del agente RAG y base de conocimiento"

# Tipo de búsqueda: DEFAULT o SEMANTIC
agentcore_gateway_search_type = "SEMANTIC"

# Nivel de excepciones: PARTIAL, FULL, DEBUG
agentcore_gateway_exception_level = "DEBUG"

# ==============================================================================
# Gateway Target (Tool expuesta)
# ==============================================================================

agentcore_create_gateway_target = true

agentcore_gateway_target_tool_name = "knowledge_base_search"

agentcore_gateway_target_tool_description = "Busca información en la base de conocimiento empresarial usando búsqueda semántica"

agentcore_gateway_target_tool_input_description = "Parámetros de entrada para la búsqueda en base de conocimiento"

agentcore_gateway_target_tool_input_properties = [
  {
    name        = "query"
    type        = "string"
    description = "La pregunta o términos de búsqueda"
    required    = true
  },
  {
    name        = "tenant_id"
    type        = "string"
    description = "Identificador del tenant/organización"
    required    = true
  },
  {
    name        = "agent_id"
    type        = "string"
    description = "Identificador del agente configurado"
    required    = true
  }
]
