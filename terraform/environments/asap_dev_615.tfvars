# ==============================================================================
# Instalación limpia — cuenta 615216531593, perfil asap_dev
# VPC por defecto us-east-1 (actualizar si usáis VPC dedicada)
# ==============================================================================

region      = "us-east-1"
aws_region  = "us-east-1"
aws_profile = "asap_dev"
environment = "dev"

# Red: default VPC en 615216531593 (dos AZ distintas para Aurora/Lambda)
vpc_id  = "vpc-0e10ffaf0f96cbaab"
subnets = ["subnet-0ea7992f250c3aa27", "subnet-0366071edda409f53"]

# Aurora PostgreSQL — cambiar master_password en producción
master_username     = "dev_master"
master_password     = "CambiarEstaPasswordEnProd123!"
engine_version      = "14.20"
aurora_min_capacity = 0.5
aurora_max_capacity = 4

enable_s3_cors       = false
cors_allowed_origins = ["*"]

# Lambdas: no definir DB_* aquí; main.tf inyecta endpoint Aurora vía base_db_env_vars
lambda_embeddings_config = {
  timeout                = 900
  memory_size            = 1024
  ephemeral_storage_size = 1024
}

lambda_embeddings_env_vars = {
  EMBEDDINGS_MODEL      = "cohere.embed-v4:0"
  MAX_EMBED_TEXT_LENGTH = "20000"
}

lambda_query_config = {
  timeout                = 120
  memory_size            = 512
  ephemeral_storage_size = 512
}

lambda_query_env_vars = {
  EMBEDDINGS_MODEL      = "cohere.embed-v4:0"
  OUTPUT_TOKENS         = "2048"
  MAX_EMBED_TEXT_LENGTH = "20000"
  MAIN_LLM_MODEL        = "openai.gpt-oss-120b-1:0"
  FALLBACK_LLM_MODEL    = "openai.gpt-oss-20b-1:0"
}

# AgentCore — desactivado en arranque mínimo; activar cuando tengáis imagen ECR en 615
create_agentcore = false

agentcore_name_prefix = "rag_agent"

agentcore_create_runtime        = false
agentcore_runtime_container_uri = "615216531593.dkr.ecr.us-east-1.amazonaws.com/rag-agent:latest"
agentcore_runtime_description   = "RAG Agent Runtime"
agentcore_runtime_network_mode  = "PUBLIC"
agentcore_runtime_protocol      = "HTTP"
agentcore_runtime_idle_timeout  = 3600
agentcore_runtime_max_lifetime  = 28800
agentcore_runtime_environment_variables = {
  LOG_LEVEL   = "INFO"
  ENVIRONMENT = "dev"
}
agentcore_create_runtime_endpoint = false

agentcore_create_cognito = false

agentcore_create_memory = false

agentcore_create_gateway = false

agentcore_create_gateway_target = false
