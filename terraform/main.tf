terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.20.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
  }
  required_version = ">= 1.3.0"

  # Uncomment to use S3 backend for state
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "rag-agents/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
}

locals {
  env = terraform.workspace
  
  common_tags = {
    Environment = var.environment
    Project     = "rag-agents"
    ManagedBy   = "terraform"
  }

  # Lambda source paths (relative to terraform directory)
  lambda_embeddings_path = "${path.module}/../apps/rag_lmbd_embeddings"
  lambda_query_path      = "${path.module}/../apps/rag_lmbd_query"

  # Base environment variables (computed from other resources)
  base_db_env_vars = {
    DB_HOST = module.aurora.cluster_endpoint
    DB_PORT = "5432"
    DB_NAME = "ragdb_${var.environment}"
    DB_USER = var.master_username
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

  bucket_name      = "rag-documents-${var.environment}-${data.aws_caller_identity.current.account_id}"
  enable_lifecycle = true
  enable_cors      = var.enable_s3_cors
  cors_allowed_origins = var.cors_allowed_origins

  tags = local.common_tags
}

# ==============================================================================
# VPC Endpoints (para acceso desde Lambda en VPC)
# ==============================================================================

# Obtener route tables de las subnets
data "aws_subnet" "selected" {
  count = length(var.subnets)
  id    = var.subnets[count.index]
}

data "aws_route_table" "selected" {
  count     = length(var.subnets)
  subnet_id = var.subnets[count.index]
}

# VPC Endpoint para S3 (Gateway type - gratuito)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  
  route_table_ids = distinct(data.aws_route_table.selected[*].id)
  
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

# VPC Endpoint para Bedrock Runtime (Interface type)
resource "aws_vpc_endpoint" "bedrock" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnets
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "bedrock-endpoint-${var.environment}"
  })
}

# Security Group para VPC Endpoints de tipo Interface
resource "aws_security_group" "vpc_endpoints" {
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

  function_name = "rag_lmbd_embeddings-${var.environment}"
  description   = "Processes PDF documents, generates embeddings and stores in PostgreSQL"
  handler       = "index.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_embeddings_config.timeout
  memory_size   = var.lambda_embeddings_config.memory_size
  ephemeral_storage_size = var.lambda_embeddings_config.ephemeral_storage_size

  source_path = local.lambda_embeddings_path
  environment = var.environment

  # VPC Configuration for RDS access
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = [module.aurora.security_group_id]

  environment_variables = local.lambda_embeddings_env

  # S3 Trigger
  s3_trigger_enabled = true
  s3_bucket_name     = module.s3_documents.bucket_name
  s3_bucket_arn      = module.s3_documents.bucket_arn
  s3_events          = ["s3:ObjectCreated:*"]
  s3_filter_suffix   = ".pdf"

  # IAM Permissions
  attach_policy_statements = [
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
    {
      effect = "Allow"
      actions = [
        "bedrock:InvokeModel"
      ]
      resources = [
        "arn:aws:bedrock:${var.region}::foundation-model/*"
      ]
    },
    {
      effect = "Allow"
      actions = [
        "textract:StartDocumentTextDetection",
        "textract:GetDocumentTextDetection"
      ]
      resources = ["*"]
    }
  ]

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Query (semantic search + LLM response)
# ==============================================================================

module "lambda_query" {
  source = "./modules/lambda"

  function_name = "rag_lmbd_query-${var.environment}"
  description   = "Performs semantic search and generates LLM responses"
  handler       = "index.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_query_config.timeout
  memory_size   = var.lambda_query_config.memory_size
  ephemeral_storage_size = var.lambda_query_config.ephemeral_storage_size

  source_path = local.lambda_query_path
  environment = var.environment

  # VPC Configuration for RDS access
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = [module.aurora.security_group_id]

  environment_variables = local.lambda_query_env

  # IAM Permissions - grant access to all Bedrock models
  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "bedrock:InvokeModel"
      ]
      resources = [
        "arn:aws:bedrock:${var.region}::foundation-model/*"
      ]
    }
  ]

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
