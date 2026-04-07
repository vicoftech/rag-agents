terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      # El estado remoto (p. ej. QA) puede exigir un 6.x más reciente que el lock viejo (6.28);
      # subir el mínimo y ejecutar: terraform init -upgrade
      version = ">= 6.35.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 0.24.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
    null = {
      source  = "hashicorp/null"
      version = ">= 3.2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0"
    }
    time = {
      source  = "hashicorp/time"
      version = ">= 0.9.0"
    }
  }
  required_version = ">= 1.2.0"

  # Estado remoto (bucket + DynamoDB creados con terraform/bootstrap/)
  backend "s3" {
    bucket         = "rag-agents-terraform-state-615216531593"
    key            = "rag-agents/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "rag-agents-terraform-locks"
    profile        = "asap_dev"
  }
}

# Provider configuration
# If aws_profile is empty string, Terraform will use default AWS credentials
# (from AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars or ~/.aws/credentials)
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : "default"
}

provider "awscc" {
  region  = var.aws_region
  profile = var.aws_profile != "" ? var.aws_profile : "default"
}

provider "null" {}

provider "random" {}

provider "time" {}

locals {
  env = terraform.workspace

  common_tags = {
    Environment = var.environment
    Project     = "rag-agents"
    ManagedBy   = "terraform"
  }

  # Lambda source paths (relative to terraform directory)
  lambda_embeddings_path   = "${path.module}/../apps/rag_lmbd_embeddings"
  lambda_query_path        = "${path.module}/../apps/rag_lmbd_query"
  lambda_fetcher_path      = "${path.module}/../apps/rag_lmbd_fetcher"
  lambda_bolinks_path      = "${path.module}/../apps/rag_lmbd_bolinks"
  lambda_parser_path       = "${path.module}/../apps/rag_lmbd_parser"
  lambda_s3writer_path     = "${path.module}/../apps/rag_lmbd_s3writer"
  lambda_dbwriter_path     = "${path.module}/../apps/rag_lmbd_dbwriter"
  lambda_notifier_path     = "${path.module}/../apps/rag_lmbd_notifier"
  lambda_stepfunction_path = "${path.module}/../apps/rag_lmbd_stepfunction"
  lambda_agent_path        = "${path.module}/../apps/agent"

  # Base environment variables (computed from other resources)
  base_db_env_vars = {
    DB_HOST     = module.aurora.cluster_endpoint
    DB_PORT     = "5432"
    DB_NAME     = "ragdb_${var.environment}"
    DB_USER     = var.master_username
    DB_PASSWORD = var.master_password
  }

  # Merged environment variables for each lambda
  lambda_embeddings_env = merge(
    local.base_db_env_vars,
    var.lambda_embeddings_env_vars
  )

  lambda_query_env = merge(
    local.base_db_env_vars,
    var.lambda_query_env_vars
  )

  # Modelos serverless vía AWS Marketplace (p. ej. Cohere Embed en Bedrock) requieren que el rol
  # de ejecución pueda ViewSubscriptions/Subscribe cuando Bedrock completa la suscripción.
  # Ver: https://repost.aws/knowledge-center/bedrock-serverless-models-access-denied
  lambda_bedrock_with_marketplace = [
    {
      effect = "Allow"
      actions = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
      ]
      resources = [
        "arn:aws:bedrock:${var.aws_region}::foundation-model/*"
      ]
    },
    {
      effect = "Allow"
      actions = [
        "aws-marketplace:ViewSubscriptions",
        "aws-marketplace:Subscribe",
        "aws-marketplace:Unsubscribe",
      ]
      resources = ["*"]
    },
  ]
}

# ==============================================================================
# Data Sources
# ==============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ==============================================================================
# S3 Bucket for Documents
# ==============================================================================

module "s3_documents" {
  source = "./modules/s3_documents"

  bucket_name          = "rag-documents-${var.environment}-${data.aws_caller_identity.current.account_id}"
  enable_lifecycle     = true
  enable_cors          = var.enable_s3_cors
  cors_allowed_origins = var.cors_allowed_origins

  tags = local.common_tags
}

# ==============================================================================
# VPC Endpoints (para acceso desde Lambda en VPC)
# ==============================================================================

# Route tables de la VPC (solo si creamos el endpoint Gateway S3)
data "aws_route_tables" "vpc_for_s3_endpoint" {
  count  = var.create_vpc_endpoint_s3 ? 1 : 0
  vpc_id = var.vpc_id
}

# VPC Endpoint para S3 (Gateway type - gratuito)
resource "aws_vpc_endpoint" "s3" {
  count             = var.create_vpc_endpoint_s3 ? 1 : 0
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = data.aws_route_tables.vpc_for_s3_endpoint[0].ids

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowAll"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:*"]
        Resource  = ["*"]
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "s3-endpoint-${var.environment}"
  })
}

# Security Group para VPC Endpoints de tipo Interface (Bedrock)
resource "aws_security_group" "vpc_endpoints" {
  count       = var.create_vpc_endpoint_bedrock ? 1 : 0
  name        = "vpc-endpoints-sg-${var.environment}"
  description = "Security group for VPC endpoints"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "vpc-endpoints-sg-${var.environment}"
  })
}

# VPC Endpoint para Bedrock Runtime (Interface type)
resource "aws_vpc_endpoint" "bedrock" {
  count               = var.create_vpc_endpoint_bedrock ? 1 : 0
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnets
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "bedrock-endpoint-${var.environment}"
  })
}

# ==============================================================================
# Aurora PostgreSQL (existing module)
# ==============================================================================

module "aurora" {
  source = "./modules/aurora_postgres"

  vpc_id      = var.vpc_id
  subnets     = var.subnets
  environment = var.environment

  db_name = "ragdb_${var.environment}"

  min_capacity = var.aurora_min_capacity
  max_capacity = var.aurora_max_capacity

  master_username = var.master_username
  master_password = var.master_password
  engine_version  = var.engine_version
}

# ==============================================================================
# Lambda: RAG Embeddings (triggered by S3)
# ==============================================================================

module "lambda_embeddings" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_embeddings-${var.environment}"
  description            = "Processes PDF documents, generates embeddings and stores in PostgreSQL"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = var.lambda_embeddings_config.timeout
  memory_size            = var.lambda_embeddings_config.memory_size
  ephemeral_storage_size = var.lambda_embeddings_config.ephemeral_storage_size

  source_path = local.lambda_embeddings_path
  environment = var.environment

  # VPC Configuration for RDS access
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = [module.aurora.security_group_id]

  environment_variables = local.lambda_embeddings_env

  # Use S3 for large deployment packages
  use_s3_deployment = true

  # S3 Trigger
  s3_trigger_enabled = true
  s3_bucket_name     = module.s3_documents.bucket_name
  s3_bucket_arn      = module.s3_documents.bucket_arn
  s3_events          = ["s3:ObjectCreated:*"]
  s3_filter_suffix   = ".pdf"

  # IAM Permissions
  attach_policy_statements = concat(
    [
      {
        effect = "Allow"
        actions = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        resources = [
          module.s3_documents.bucket_arn,
          "${module.s3_documents.bucket_arn}/*"
        ]
      },
    ],
    local.lambda_bedrock_with_marketplace,
    [
      {
        effect = "Allow"
        actions = [
          "textract:StartDocumentTextDetection",
          "textract:GetDocumentTextDetection"
        ]
        resources = ["*"]
      }
    ]
  )

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Query (semantic search + LLM response)
# ==============================================================================

module "lambda_query" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_query-${var.environment}"
  description            = "Performs semantic search and generates LLM responses"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = var.lambda_query_config.timeout
  memory_size            = var.lambda_query_config.memory_size
  ephemeral_storage_size = var.lambda_query_config.ephemeral_storage_size

  source_path = local.lambda_query_path
  environment = var.environment

  # VPC Configuration for RDS access
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = [module.aurora.security_group_id]

  # Use S3 for large deployment packages
  use_s3_deployment = true
  s3_bucket_name    = module.s3_documents.bucket_name

  environment_variables = merge(local.lambda_query_env, {
    DOCUMENTS_S3_BUCKET = module.s3_documents.bucket_name
  })

  # IAM Permissions - Bedrock + Marketplace + S3 presigned URLs for documents bucket
  attach_policy_statements = concat(
    local.lambda_bedrock_with_marketplace,
    [
      {
        effect = "Allow"
        actions = [
          "s3:GetObject",
        ]
        resources = [
          "${module.s3_documents.bucket_arn}/*",
        ]
      },
    ],
  )

  tags = local.common_tags
}

# ==============================================================================
# Cognito + API Gateway for RAG Query (/query)
# ==============================================================================

module "cognito_query" {
  source = "./modules/cognito"

  name        = "rag-agents-query"
  environment = var.environment
  aws_region  = var.aws_region

  tags = local.common_tags
}

module "api_gateway_query" {
  source = "./modules/api_gateway"

  api_name        = "rag-query-api-${var.environment}"
  api_description = "API Gateway for RAG Query with JWT authentication"
  environment     = var.environment
  aws_region      = var.aws_region

  lambda_function_name = module.lambda_query.function_name
  lambda_invoke_arn    = module.lambda_query.invoke_arn

  cognito_user_pool_client_id = module.cognito_query.user_pool_client_id
  cognito_endpoint            = module.cognito_query.cognito_endpoint

  cors_allowed_origins = ["*"]
  cors_allowed_methods = ["GET", "POST", "OPTIONS"]
  cors_allowed_headers = ["*"]

  tags = local.common_tags
}

# ==============================================================================
# DynamoDB Table for Documents
# ==============================================================================

resource "aws_dynamodb_table" "documents" {
  name         = "rag-documents-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "entity_type"
    type = "S"
  }

  attribute {
    name = "site_id"
    type = "S"
  }

  attribute {
    name = "date"
    type = "S"
  }

  global_secondary_index {
    name            = "SiteDateIndex"
    hash_key        = "site_id"
    range_key       = "date"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "EntityTypeIndex"
    hash_key        = "entity_type"
    range_key       = "PK"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "EntityDateIndex"
    hash_key        = "entity_type"
    range_key       = "date"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Parser (HTML to PDF links extractor)
# ==============================================================================

module "lambda_parser" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_parser-${var.environment}"
  description            = "Extracts PDF links from HTML content"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 60
  memory_size            = 256
  ephemeral_storage_size = 512

  source_path = local.lambda_parser_path
  environment = var.environment

  tags = local.common_tags
}

module "lambda_s3writer" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_s3writer-${var.environment}"
  description            = "Downloads PDFs and uploads to S3"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 900 # 15 minutos para descargar múltiples archivos
  memory_size            = 1024
  ephemeral_storage_size = 1024

  source_path = local.lambda_s3writer_path
  environment = var.environment

  environment_variables = {
    S3_BUCKET_NAME      = module.s3_documents.bucket_name
    REQUEST_TIMEOUT      = "60"
    MAX_FILE_SIZE        = "52428800"  # 50MB
    TENANT_ID           = "7c9aa113-ecf2-4449-a955-d91c76e7ee27"
    SITE_NAME           = "boletin"
  }

  # IAM Permissions
  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ]
      resources = [
        "${module.s3_documents.bucket_arn}/*"
      ]
    }
  ]

  tags = local.common_tags
}

module "lambda_dbwriter" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_dbwriter-${var.environment}"
  description            = "Upserts document metadata to DynamoDB"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 300 # 5 minutos para batch writes
  memory_size            = 256
  ephemeral_storage_size = 512

  source_path = local.lambda_dbwriter_path
  environment = var.environment

  environment_variables = {
    DYNAMODB_TABLE_NAME = aws_dynamodb_table.documents.name
  }

  # IAM Permissions
  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "dynamodb:PutItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:UpdateItem"
      ]
      resources = [
        aws_dynamodb_table.documents.arn
      ]
    }
  ]

  tags = local.common_tags
}

resource "aws_sns_topic" "rag_notifications" {
  name = "rag-pipeline-notifications-${var.environment}"

  tags = local.common_tags
}

module "lambda_notifier" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_notifier-${var.environment}"
  description            = "Sends pipeline notifications via SNS"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 60
  memory_size            = 256
  ephemeral_storage_size = 512

  source_path = local.lambda_notifier_path
  environment = var.environment

  environment_variables = {
    SNS_TOPIC_ARN      = aws_sns_topic.rag_notifications.arn
    NOTIFICATION_EMAIL = var.notification_email
  }

  # IAM Permissions
  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "sns:Publish"
      ]
      resources = [
        aws_sns_topic.rag_notifications.arn
      ]
    }
  ]

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Fetcher (Boletín Oficial scraper)
# ==============================================================================

module "lambda_fetcher" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_fetcher-${var.environment}"
  description            = "Fetches HTML content from Boletín Oficial by date"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 60
  memory_size            = 512
  ephemeral_storage_size = 512

  source_path = local.lambda_fetcher_path
  environment = var.environment

  environment_variables = {
    BOLETIN_BASE_URL = var.boletin_base_url
    DEFAULT_SECTION  = var.boletin_default_section
    REQUEST_TIMEOUT  = var.boletin_request_timeout
  }

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Bolinks (Boletín Oficial Links Processor)
# ==============================================================================

module "lambda_bolinks" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_bolinks-${var.environment}"
  description            = "Processes Boletín Oficial links and extracts structured data"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 180
  memory_size            = 512
  ephemeral_storage_size = 512

  source_path = local.lambda_bolinks_path
  environment = var.environment

  environment_variables = {
    BOLETIN_BASE_URL = var.boletin_base_url
    DEFAULT_SECTION  = var.boletin_default_section
    REQUEST_TIMEOUT  = var.boletin_request_timeout
  }

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Step Function (Pipeline Orchestrator)
# ==============================================================================

module "lambda_stepfunction" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_stepfunction-${var.environment}"
  description            = "Orchestrates the complete RAG pipeline: fetcher → parser → s3writer → dbwriter → notifier"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 900 # 15 minutos para ejecutar todo el pipeline
  memory_size            = 512
  ephemeral_storage_size = 1024

  source_path = local.lambda_stepfunction_path
  environment = var.environment

  environment_variables = {
    FETCHER_FUNCTION_NAME  = module.lambda_fetcher.function_name
    BOLINKS_FUNCTION_NAME  = module.lambda_bolinks.function_name
    PARSER_FUNCTION_NAME   = module.lambda_parser.function_name
    S3WRITER_FUNCTION_NAME = module.lambda_s3writer.function_name
    DBWRITER_FUNCTION_NAME = module.lambda_dbwriter.function_name
    NOTIFIER_FUNCTION_NAME = module.lambda_notifier.function_name
  }

  # IAM Permissions - permisos para invocar otras lambdas
  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "lambda:InvokeFunction"
      ]
      resources = [
        module.lambda_fetcher.function_arn,
        module.lambda_bolinks.function_arn,
        module.lambda_parser.function_arn,
        module.lambda_s3writer.function_arn,
        module.lambda_dbwriter.function_arn,
        module.lambda_notifier.function_arn
      ]
    }
  ]

  tags = local.common_tags
}

# ==============================================================================
# Bedrock Agent Core
# ==============================================================================

module "bedrock_agent" {
  source = "./modules/bedrock_agent"

  count = var.create_agentcore ? 1 : 0

  # General configuration
  function_name          = "rag-agent-${var.environment}"
  description            = "Bedrock Agent Core handler for RAG agent"
  handler                = "api_gateway_handler.lambda_handler"
  runtime                = "python3.12"
  timeout                = 300
  memory_size            = 1024
  ephemeral_storage_size = 1024

  source_path = local.lambda_agent_path
  environment = var.environment

  # VPC Configuration (optional, same as other lambdas)
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = length(var.subnets) > 0 ? [module.aurora.security_group_id] : []

  environment_variables = merge(
    {
      AGENT_MODEL_ID    = var.agent_model_id
      AGENT_NAME        = var.agent_name
      LAMBDA_QUERY      = module.lambda_query.function_name
      LAMBDA_EMBEDDINGS = module.lambda_embeddings.function_name
    },
    var.agent_environment_variables
  )

  agent_name                 = "${var.agent_name}-${var.environment}"
  agent_description          = "RAG Agent deployed via Bedrock Agent Core"
  agent_model_id             = var.agent_model_id
  region                     = var.aws_region
  lambda_query_function_name = module.lambda_query.function_name

  tags = local.common_tags
}

# ==============================================================================
# API Gateway with JWT Authentication
# ==============================================================================

module "api_gateway" {
  source = "./modules/api_gateway_jwt"

  count = var.create_agentcore ? 1 : 0

  api_name        = "rag-agent-api-${var.environment}"
  api_description = "API Gateway for RAG Agent with JWT authentication"
  environment     = var.environment
  region          = var.aws_region

  lambda_function_arn  = module.bedrock_agent[0].lambda_function_arn
  lambda_function_name = module.bedrock_agent[0].lambda_function_name
  lambda_invoke_arn    = module.bedrock_agent[0].lambda_invoke_arn

  create_cognito_user_pool    = var.create_cognito_user_pool
  cognito_user_pool_id        = var.cognito_user_pool_id
  cognito_user_pool_client_id = var.cognito_user_pool_client_id
  cognito_user_pool_arn       = var.cognito_user_pool_arn

  cors_allowed_origins = var.cors_allowed_origins
  cors_allowed_methods = ["GET", "POST", "OPTIONS"]
  cors_allowed_headers = ["Content-Type", "Authorization"]

  tags = local.common_tags
}

# ==============================================================================
# Lambda Layer for Python Dependencies (optional, for shared deps)
# ==============================================================================

# resource "aws_lambda_layer_version" "python_deps" {
#   filename            = "${path.module}/layers/python-deps.zip"
#   layer_name          = "rag-python-deps-${var.environment}"
#   compatible_runtimes = ["python3.12"]
#   description         = "Shared Python dependencies for RAG lambdas"
# }

# ==============================================================================
# Bedrock AgentCore Module
# Based on: https://github.com/aws-ia/terraform-aws-agentcore
# ==============================================================================

module "agentcore" {
  source = "./modules/agentcore"

  # Only create if enabled
  count = var.create_agentcore ? 1 : 0

  # General configuration
  name_prefix = var.agentcore_name_prefix
  environment = var.environment
  tags        = local.common_tags

  # Runtime configuration (ECR image)
  create_runtime             = var.agentcore_create_runtime
  runtime_container_uri      = var.agentcore_runtime_container_uri
  runtime_description        = var.agentcore_runtime_description
  runtime_network_mode       = var.agentcore_runtime_network_mode
  runtime_subnet_ids         = var.agentcore_runtime_network_mode == "VPC" ? var.subnets : []
  runtime_security_group_ids = var.agentcore_runtime_network_mode == "VPC" ? [module.aurora.security_group_id] : []
  runtime_protocol           = var.agentcore_runtime_protocol
  runtime_idle_timeout       = var.agentcore_runtime_idle_timeout
  runtime_max_lifetime       = var.agentcore_runtime_max_lifetime
  runtime_environment_variables = merge(
    {
      LAMBDA_QUERY      = module.lambda_query.function_name
      LAMBDA_EMBEDDINGS = module.lambda_embeddings.function_name
      AGENT_NAME        = var.agent_name
      AGENT_MODEL_ID    = var.agent_model_id
    },
    var.agentcore_runtime_environment_variables
  )
  lambda_function_arns = [
    module.lambda_query.function_arn,
    module.lambda_embeddings.function_arn
  ]

  # Runtime Endpoint
  create_runtime_endpoint = var.agentcore_create_runtime_endpoint

  # Cognito (Security)
  create_cognito                      = var.agentcore_create_cognito
  cognito_user_pool_id                = var.agentcore_cognito_user_pool_id
  cognito_client_id                   = var.agentcore_cognito_client_id
  cognito_discovery_url               = var.agentcore_cognito_discovery_url
  cognito_allowed_audience            = var.agentcore_cognito_allowed_audience
  cognito_password_policy             = var.agentcore_cognito_password_policy
  cognito_mfa_configuration           = var.agentcore_cognito_mfa_configuration
  cognito_callback_urls               = var.agentcore_cognito_callback_urls
  cognito_logout_urls                 = var.agentcore_cognito_logout_urls
  cognito_token_validity_hours        = var.agentcore_cognito_token_validity_hours
  cognito_refresh_token_validity_days = var.agentcore_cognito_refresh_token_validity_days

  # Memory (Short-term and Long-term)
  create_memory                     = var.agentcore_create_memory
  memory_description                = var.agentcore_memory_description
  memory_event_expiry_days          = var.agentcore_memory_event_expiry_days
  memory_kms_key_arn                = var.agentcore_memory_kms_key_arn
  memory_enable_semantic            = var.agentcore_memory_enable_semantic
  memory_semantic_namespaces        = var.agentcore_memory_semantic_namespaces
  memory_enable_summary             = var.agentcore_memory_enable_summary
  memory_summary_namespaces         = var.agentcore_memory_summary_namespaces
  memory_enable_user_preference     = var.agentcore_memory_enable_user_preference
  memory_user_preference_namespaces = var.agentcore_memory_user_preference_namespaces
  memory_custom_strategy            = var.agentcore_memory_custom_strategy

  # Gateway (REST API)
  create_gateway          = var.agentcore_create_gateway
  gateway_description     = var.agentcore_gateway_description
  gateway_instructions    = var.agentcore_gateway_instructions
  gateway_search_type     = var.agentcore_gateway_search_type
  gateway_mcp_versions    = var.agentcore_gateway_mcp_versions
  gateway_kms_key_arn     = var.agentcore_gateway_kms_key_arn
  gateway_exception_level = var.agentcore_gateway_exception_level

  # Gateway Target
  create_gateway_target                 = var.agentcore_create_gateway_target
  gateway_target_lambda_arn             = module.lambda_query.function_arn
  gateway_target_tool_name              = var.agentcore_gateway_target_tool_name
  gateway_target_tool_description       = var.agentcore_gateway_target_tool_description
  gateway_target_tool_input_description = var.agentcore_gateway_target_tool_input_description
  gateway_target_tool_input_properties  = var.agentcore_gateway_target_tool_input_properties
}

# ==============================================================================
# Outputs
# ==============================================================================

output "lambda_stepfunction_function_name" {
  description = "Name of the step function orchestrator Lambda"
  value       = module.lambda_stepfunction.function_name
}

output "lambda_stepfunction_function_arn" {
  description = "ARN of the step function orchestrator Lambda"
  value       = module.lambda_stepfunction.function_arn
}

output "lambda_stepfunction_invoke_arn" {
  description = "Invoke ARN of the step function orchestrator Lambda"
  value       = module.lambda_stepfunction.invoke_arn
}

output "lambda_bolinks_function_name" {
  description = "Name of the bolinks Lambda"
  value       = module.lambda_bolinks.function_name
}

output "lambda_bolinks_function_arn" {
  description = "ARN of the bolinks Lambda"
  value       = module.lambda_bolinks.function_arn
}

output "lambda_bolinks_invoke_arn" {
  description = "Invoke ARN of the bolinks Lambda"
  value       = module.lambda_bolinks.invoke_arn
}
