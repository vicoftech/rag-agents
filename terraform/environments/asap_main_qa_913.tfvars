# ==============================================================================
# QA — cuenta 913123310997, perfil asap_main
# VPC principal (subnets privadas us-east-1b / us-east-1c)
# Estado remoto: environments/backend-qa-913.hcl
# ==============================================================================

region      = "us-east-1"
aws_region  = "us-east-1"
aws_profile = "asap_main"
environment = "qa"

vpc_id  = "vpc-0220b63692086a550"
subnets = ["subnet-04cc462043523dcb9", "subnet-0254c9d900c8b2fdc"]

# La VPC 913 ya tiene endpoint S3 (gateway) y bedrock-runtime (interface + private DNS)
create_vpc_endpoint_s3      = false
create_vpc_endpoint_bedrock = false

master_username     = "qa_master"
master_password     = "CambiarEstaPasswordQA123!"
engine_version      = "14.20"
aurora_min_capacity = 0.5
aurora_max_capacity = 4

enable_s3_cors       = false
cors_allowed_origins = ["*"]

lambda_embeddings_config = {
  timeout                = 900
  memory_size            = 1024
  ephemeral_storage_size = 1024
}

# Alineado con environments/prod.tfvars (misma receta S3 + modelo).
lambda_embeddings_env_vars = {
  EMBEDDINGS_MODEL         = "cohere.embed-v4:0"
  MAX_EMBED_TEXT_LENGTH    = "20000"
  S3_USE_REGIONAL_ENDPOINT = "1"
  S3_CONNECT_TIMEOUT       = "15"
  S3_READ_TIMEOUT          = "60"
  S3_MAX_ATTEMPTS          = "4"
  S3_RETRY_MODE            = "standard"
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

create_agentcore = false

agentcore_name_prefix = "rag_agent"

agentcore_create_runtime        = false
agentcore_runtime_container_uri = "913123310997.dkr.ecr.us-east-1.amazonaws.com/rag-agent:latest"
agentcore_runtime_description   = "RAG Agent Runtime"
agentcore_runtime_network_mode  = "PUBLIC"
agentcore_runtime_protocol      = "HTTP"
agentcore_runtime_idle_timeout  = 3600
agentcore_runtime_max_lifetime  = 28800
agentcore_runtime_environment_variables = {
  LOG_LEVEL   = "INFO"
  ENVIRONMENT = "qa"
}
agentcore_create_runtime_endpoint = false

agentcore_create_cognito        = false
agentcore_create_memory         = false
agentcore_create_gateway        = false
agentcore_create_gateway_target = false
