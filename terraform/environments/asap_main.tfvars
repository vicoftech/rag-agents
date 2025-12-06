# ==============================================================================
# ASAP Main Environment Configuration
# ==============================================================================

# General
region      = "us-east-1"
aws_profile = "asap_main"
environment = "dev"

# Network
vpc_id  = "vpc-0220b63692086a550"
subnets = ["subnet-04cc462043523dcb9", "subnet-0254c9d900c8b2fdc"]

# Aurora PostgreSQL
master_username     = "dev_master"
master_password     = "DevPassword123!"
engine_version      = "14.11"
aurora_min_capacity = 0.5
aurora_max_capacity = 4

# S3
enable_s3_cors       = false
cors_allowed_origins = ["*"]

# ==============================================================================
# Lambda Embeddings Configuration
# ==============================================================================

lambda_embeddings_config = {
  timeout                = 900   # 15 minutes for large PDFs
  memory_size            = 1024
  ephemeral_storage_size = 1024
}

lambda_embeddings_env_vars = {
  EMBEDDINGS_MODEL = "cohere.embed-v4:0"
  # Agrega más variables de entorno aquí según necesites
  # LOG_LEVEL = "INFO"
  DB_NAME = "postgres"
  DB_USER = "dev_master"
  DB_PASSWORD = "DevPassword123!"
  DB_HOST = "aurora-pg-dev.cluster-ch7yo6tzxi4l.us-east-1.rds.amazonaws.com"
  DB_PORT = "5432"
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
   DB_NAME = "postgres"
   DB_USER = "dev_master"
   DB_PASSWORD = "DevPassword123!"
   DB_HOST = "aurora-pg-dev.cluster-ch7yo6tzxi4l.us-east-1.rds.amazonaws.com"
   DB_PORT = "5432"
   MAIN_LLM_MODEL = "openai.gpt-oss-120b-1:0"
   FALLBACK_LLM_MODEL ="openai.gpt-oss-20b-1:0"
   #EMBEDDINGS_MODEL = "amazon.titan-embed-text-v2:0"
   EMBEDDINGS_MODEL = "cohere.embed-v4:0"
   OUTPUT_TOKENS =  "2048"
   MAX_EMBED_TEXT_LENGTH = "20000"
}
