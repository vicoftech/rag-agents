terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
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
  required_version = ">= 1.5.0"

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
  use_existing_db = var.create_aurora_cluster == false

  common_tags = {
    Environment = var.environment
    Project     = "rag-agents"
    ManagedBy   = "terraform"
  }

  # Lambda source paths (relative to terraform directory)
  lambda_embeddings_path         = "${path.module}/../apps/rag_lmbd_embeddings"
  lambda_embeddings_enqueue_path = "${path.module}/../apps/rag_lmbd_embeddings_enqueue"
  lambda_query_path              = "${path.module}/../apps/rag_lmbd_query"
  lambda_fetcher_path            = "${path.module}/../apps/rag_lmbd_fetcher"
  lambda_bolinks_path            = "${path.module}/../apps/rag_lmbd_bolinks"
  lambda_anmatlinks_path         = "${path.module}/../apps/rag_lmbd_anmatlinks"
  lambda_parser_path             = "${path.module}/../apps/rag_lmbd_parser"
  lambda_s3writer_path           = "${path.module}/../apps/rag_lmbd_s3writer"
  lambda_dbwriter_path           = "${path.module}/../apps/rag_lmbd_dbwriter"
  lambda_notifier_path           = "${path.module}/../apps/rag_lmbd_notifier"
  lambda_obtener_alertas_path    = "${path.module}/../apps/rag_lmbd_obtener_alertas"
  lambda_stepfunction_path       = "${path.module}/../apps/rag_lmbd_stepfunction"
  lambda_agent_path              = "${path.module}/../apps/agent"

  # Base environment variables (computed from other resources)
  db_host              = local.use_existing_db ? var.existing_db_host : module.aurora[0].cluster_endpoint
  db_port              = local.use_existing_db ? tostring(var.existing_db_port) : "5432"
  db_name              = local.use_existing_db ? var.existing_db_name : "ragdb_${var.environment}"
  db_security_group_id = local.use_existing_db ? var.existing_db_security_group_id : module.aurora[0].security_group_id

  base_db_env_vars = {
    DB_HOST      = local.db_host
    DB_PORT      = local.db_port
    DB_NAME      = local.db_name
    DB_USER      = var.master_username
    DB_PASSWORD  = var.master_password
    DB_SECRET_ID = var.db_secret_id
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

  lambda_db_secret_policy = var.db_secret_id != "" ? [
    {
      effect = "Allow"
      actions = [
        "secretsmanager:GetSecretValue",
      ]
      resources = [var.db_secret_id]
    }
  ] : []
}

# Estado remoto S3 está particionado por workspace ([env:/<name>/...]). Si apliás prod.tfvars
# con workspace "default", los recursos y el código divergen del intento sin error obvio.
check "workspace_aligned_with_tfvars_environment" {
  assert {
    condition = (
      terraform.workspace == var.environment
      || (terraform.workspace == "default" && var.environment == "dev")
    )
    error_message = <<-EOT
      Workspace Terraform "${terraform.workspace}" no alinea con var.environment="${var.environment}" del tfvars.
      Ej.: terraform workspace select ${var.environment} antes de plan/apply.
      Excepción explícita: workspace "default" solo con environment="dev".
    EOT
  }
}

# ==============================================================================
# Data Sources
# ==============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ==============================================================================
# S3 Bucket for Documents
# ==============================================================================

data "aws_s3_bucket" "documents_existing" {
  count  = var.create_documents_bucket ? 0 : 1
  bucket = "rag-documents-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

module "s3_documents" {
  count  = var.create_documents_bucket ? 1 : 0
  source = "./modules/s3_documents"

  bucket_name          = "rag-documents-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy        = var.s3_bucket_force_destroy
  enable_lifecycle     = true
  enable_cors          = var.enable_s3_cors
  cors_allowed_origins = var.cors_allowed_origins

  tags = local.common_tags
}

locals {
  documents_bucket_name = var.create_documents_bucket ? module.s3_documents[0].bucket_name : data.aws_s3_bucket.documents_existing[0].bucket
  documents_bucket_arn  = var.create_documents_bucket ? module.s3_documents[0].bucket_arn : data.aws_s3_bucket.documents_existing[0].arn
  rag_lambda_security_group_id = (
    var.existing_rag_lambda_security_group_id != ""
    ? var.existing_rag_lambda_security_group_id
    : aws_security_group.rag_lambda[0].id
  )
}

# ==============================================================================
# Sparticuz Chromium Lambda layer (rag_lmbd_anmatlinks / Playwright)
# ==============================================================================

module "sparticuz_chromium_layer" {
  source = "./modules/sparticuz_chromium_layer"

  environment    = var.environment
  s3_bucket_name = local.documents_bucket_name
  layer_zip_url  = var.sparticuz_chromium_layer_zip_url
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

# Si el Gateway VPCE S3 ya existe en la VPC (create_vpc_endpoint_s3=false), asociar las tablas de
# rutas de var.subnets al endpoint cuando falte alguna (p. ej. subnet nueva sin ruta al prefijo S3).
module "s3_vpce_subnet_route_table_associations" {
  count  = var.create_vpc_endpoint_s3 ? 0 : 1
  source = "./modules/s3_vpce_route_table_associations"

  vpc_id     = var.vpc_id
  aws_region = var.aws_region
  subnet_ids = var.subnets
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

# Security group dedicado para Lambdas en VPC (S3/Bedrock/Secrets/Textract/etc.).
# No reutilizar el SG de Aurora en las Lambdas: suele carecer de egress y rompe GetObject a S3.
resource "aws_security_group" "rag_lambda" {
  count       = var.existing_rag_lambda_security_group_id != "" ? 0 : 1
  name        = "rag-lambda-${var.environment}-sg"
  description = "RAG Lambdas en VPC: egress a APIs AWS (S3 gateway, Bedrock, Secrets, Textract)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Egreso a Internet / endpoints (HTTPS)"
  }

  tags = merge(local.common_tags, {
    Name = "rag-lambda-${var.environment}-sg"
  })
}

# Secrets Manager + Textract: APIs regionales por HTTPS; sin NAT solo alcanzables vía Interface VPCE
# (la Lambda cuelga al leer el secreto de DB o al usar Textract en PDFs grandes).
resource "aws_security_group" "rag_interface_endpoints" {
  count       = var.create_vpc_endpoint_secrets_textract ? 1 : 0
  name        = "rag-vpce-if-${var.environment}-sg"
  description = "HTTPS 443 desde Lambdas RAG hacia Interface VPC endpoints (Secrets, Textract)"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTPS desde Lambdas RAG"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [local.rag_lambda_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Respuesta desde el servicio AWS"
  }

  tags = merge(local.common_tags, {
    Name = "rag-vpce-if-${var.environment}"
  })
}

resource "aws_vpc_endpoint" "secretsmanager" {
  count               = var.create_vpc_endpoint_secrets_textract ? 1 : 0
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnets
  security_group_ids  = [aws_security_group.rag_interface_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "secretsmanager-endpoint-${var.environment}"
  })
}

resource "aws_vpc_endpoint" "textract" {
  count               = var.create_vpc_endpoint_secrets_textract ? 1 : 0
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.textract"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnets
  security_group_ids  = [aws_security_group.rag_interface_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "textract-endpoint-${var.environment}"
  })
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_rag_lambda" {
  security_group_id            = local.db_security_group_id
  referenced_security_group_id = local.rag_lambda_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL desde Lambdas RAG"
}

# ==============================================================================
# Aurora PostgreSQL (existing module)
# ==============================================================================

module "aurora" {
  count  = var.create_aurora_cluster ? 1 : 0
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
# Lambda: RAG Embeddings (rag_lmbd_embeddings-async, consume SQS)
# Ver: module.lambda_embeddings_enqueue, aws_s3_bucket_notification documents_to_embeddings_queue
# ==============================================================================

module "lambda_embeddings_async" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_embeddings-async-${var.environment}"
  description            = "Processes PDF documents, generates embeddings and stores in PostgreSQL (async queue consumer)"
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
  security_group_ids = [local.rag_lambda_security_group_id]

  environment_variables = local.lambda_embeddings_env

  # Use S3 for large deployment packages
  use_s3_deployment = true
  s3_bucket_name    = local.documents_bucket_name

  s3_trigger_enabled = false

  # SQS: un PDF por invocación; concurrencia vía var (backpressure; subir con cuidado: Bedrock/Textract/DB)
  sqs_trigger_enabled     = true
  sqs_queue_arn           = aws_sqs_queue.embeddings_ingest.arn
  sqs_batch_size          = 1
  sqs_maximum_concurrency = var.lambda_embeddings_sqs_concurrency

  reserved_concurrent_executions = var.lambda_embeddings_reserved_concurrency

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
          local.documents_bucket_arn,
          "${local.documents_bucket_arn}/*"
        ]
      },
    ],
    local.lambda_db_secret_policy,
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
  security_group_ids = [local.rag_lambda_security_group_id]

  # Use S3 for large deployment packages
  use_s3_deployment = true
  s3_bucket_name    = local.documents_bucket_name

  environment_variables = merge(local.lambda_query_env, {
    DOCUMENTS_S3_BUCKET = local.documents_bucket_name
  })

  # IAM Permissions - Bedrock + Marketplace + S3 presigned URLs for documents bucket
  attach_policy_statements = concat(
    local.lambda_bedrock_with_marketplace,
    local.lambda_db_secret_policy,
    [
      {
        effect = "Allow"
        actions = [
          "s3:GetObject",
        ]
        resources = [
          "${local.documents_bucket_arn}/*",
        ]
      },
    ],
  )

  tags = local.common_tags
}

# ==============================================================================
# Lambda: Obtener Alertas (reads active searches from PostgreSQL)
# ==============================================================================

module "lambda_obtener_alertas" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_obtener_alertas-${var.environment}"
  description            = "Obtiene alertas activas desde PostgreSQL"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 60
  memory_size            = 512
  ephemeral_storage_size = 512

  source_path = local.lambda_obtener_alertas_path
  environment = var.environment

  # Debe vivir en la misma VPC que el PostgreSQL del ambiente.
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnets
  security_group_ids = var.lambda_obtener_alertas_security_group_ids

  use_s3_deployment = true
  s3_bucket_name    = local.documents_bucket_name

  # Esta Lambda apunta a una BD externa gestionada fuera de este proyecto Terraform.
  # Se define de forma agnóstica en lambda_obtener_alertas_db y aquí se mapea al
  # formato legacy esperado por la función (DB_HOST_QA/PROD/DEV, etc.).
  environment_variables = merge(
    {
      ENVIRONMENT                               = var.environment
      ("DB_HOST_${upper(var.environment)}")     = var.lambda_obtener_alertas_db.host
      ("DB_PORT_${upper(var.environment)}")     = tostring(var.lambda_obtener_alertas_db.port)
      ("DB_USER_${upper(var.environment)}")     = var.lambda_obtener_alertas_db.user
      ("DB_PASSWORD_${upper(var.environment)}") = var.lambda_obtener_alertas_db.password
      ("DB_NAME_${upper(var.environment)}")     = var.lambda_obtener_alertas_db.database
      ("DB_SSLMODE_${upper(var.environment)}")  = try(var.lambda_obtener_alertas_db.sslmode, "require")
    },
    var.lambda_obtener_alertas_env_vars
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

# DLQ: tras maxReceiveCount reintentos SQS→Lambda, mensaje a cola de fallos
resource "aws_sqs_queue" "alert_s3writer_dlq" {
  name = "alert-s3writer-dlq-${var.environment}"
  tags = merge(local.common_tags, {
    Name = "alert-s3writer-dlq-${var.environment}"
  })
}

# SQS: trigger for rag_lmbd_s3writer (alert processing; Step Function envía aquí)
resource "aws_sqs_queue" "alert_s3writer" {
  name                       = "alert-s3writer-${var.environment}"
  visibility_timeout_seconds = 5400 # >= 6 × Lambda timeout (900s) per AWS guidance

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.alert_s3writer_dlq.arn
    maxReceiveCount     = 3
  })

  tags = merge(local.common_tags, {
    Name = "alert-s3writer-${var.environment}"
  })
}

# Step Function: anmatlinks → mensaje a cola → s3writer (async, no invoca s3writer en la SFN)
module "anmat_s3_stepfunction" {
  source = "./modules/anmat_s3_stepfunction"

  state_machine_name       = "rag-anmat-to-s3writer-${var.environment}"
  anmat_function_arn       = module.lambda_anmatlinks.function_arn
  anmat_function_name      = module.lambda_anmatlinks.function_name
  anmat_reset_function_arn = module.lambda_anmatlinks.function_arn
  alert_queue_url          = aws_sqs_queue.alert_s3writer.url
  alert_queue_arn          = aws_sqs_queue.alert_s3writer.arn
  tags                     = local.common_tags
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
    S3_BUCKET_NAME  = local.documents_bucket_name
    REQUEST_TIMEOUT = "60"
    MAX_FILE_SIZE   = "52428800" # 50MB
    TENANT_ID       = "7c9aa113-ecf2-4449-a955-d91c76e7ee27"
    SITE_NAME       = "boletin"
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
        "${local.documents_bucket_arn}/*"
      ]
    }
  ]

  sqs_trigger_enabled            = true
  sqs_queue_arn                  = aws_sqs_queue.alert_s3writer.arn
  sqs_batch_size                 = 1 # 1 PDF por mensaje SQS
  sqs_maximum_concurrency        = 20
  reserved_concurrent_executions = 20

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

# Step Function: Boletín (bolinks → s3writer → dbwriter) con JSONata. Nombre
# `Alerts-BoletinOficialSyncronizer-${var.environment}` (p. ej. -prod) para no
# reemplazar el state machine heredado sin sufijo creado fuera de Terraform.
module "boletin_oficial_sfn" {
  source = "./modules/boletin_oficial_sfn"

  state_machine_name = (
    var.boletin_oficial_state_machine_name_override != ""
    ? var.boletin_oficial_state_machine_name_override
    : "Alerts-BoletinOficialSyncronizer-async-${var.environment}"
  )

  bolinks_function_arn   = module.lambda_bolinks.function_arn
  s3writer_function_arn  = module.lambda_s3writer.function_arn
  dbwriter_function_arn  = module.lambda_dbwriter.function_arn
  bolinks_function_name  = module.lambda_bolinks.function_name
  s3writer_function_name = module.lambda_s3writer.function_name
  dbwriter_function_name = module.lambda_dbwriter.function_name

  tags = local.common_tags
}

# ==============================================================================
# Lambda: RAG Anmatlinks (ANMAT BuscaDispo PDF link scraper)
# ==============================================================================

module "lambda_anmatlinks" {
  source = "./modules/lambda"

  function_name          = "rag_lmbd_anmatlinks-${var.environment}"
  description            = "Scrapes ANMAT BuscaDispo for PDF links by year (Playwright/Chromium)"
  handler                = "index.handler"
  runtime                = "python3.12"
  timeout                = 900
  memory_size            = 1024
  ephemeral_storage_size = 2048

  source_path = local.lambda_anmatlinks_path
  environment = var.environment

  layers = [module.sparticuz_chromium_layer.layer_arn]

  environment_variables = {
    CHROMIUM_PACK_PATH       = "/opt/nodejs/node_modules/@sparticuz/chromium/bin"
    ANMAT_FORCED_RESOLVER_IP = "190.210.84.134"
    S3_BUCKET_NAME           = local.documents_bucket_name
  }

  use_s3_deployment = true
  s3_bucket_name    = local.documents_bucket_name

  attach_policy_statements = [
    {
      effect = "Allow"
      actions = [
        "s3:ListBucket",
      ]
      resources = [
        "arn:aws:s3:::${local.documents_bucket_name}",
      ]
    },
    {
      effect = "Allow"
      actions = [
        "s3:GetObject",
      ]
      resources = [
        "arn:aws:s3:::${local.documents_bucket_name}/*",
      ]
    },
  ]

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
  security_group_ids = length(var.subnets) > 0 ? [local.rag_lambda_security_group_id] : []

  environment_variables = merge(
    {
      AGENT_MODEL_ID    = var.agent_model_id
      AGENT_NAME        = var.agent_name
      LAMBDA_QUERY      = module.lambda_query.function_name
      LAMBDA_EMBEDDINGS = module.lambda_embeddings_async.function_name
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
  runtime_security_group_ids = var.agentcore_runtime_network_mode == "VPC" ? [local.rag_lambda_security_group_id] : []
  runtime_protocol           = var.agentcore_runtime_protocol
  runtime_idle_timeout       = var.agentcore_runtime_idle_timeout
  runtime_max_lifetime       = var.agentcore_runtime_max_lifetime
  runtime_environment_variables = merge(
    {
      LAMBDA_QUERY      = module.lambda_query.function_name
      LAMBDA_EMBEDDINGS = module.lambda_embeddings_async.function_name
      AGENT_NAME        = var.agent_name
      AGENT_MODEL_ID    = var.agent_model_id
    },
    var.agentcore_runtime_environment_variables
  )
  lambda_function_arns = [
    module.lambda_query.function_arn,
    module.lambda_embeddings_async.function_arn
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

output "lambda_anmatlinks_function_name" {
  description = "Name of the anmatlinks Lambda"
  value       = module.lambda_anmatlinks.function_name
}

output "lambda_anmatlinks_function_arn" {
  description = "ARN of the anmatlinks Lambda"
  value       = module.lambda_anmatlinks.function_arn
}

output "lambda_anmatlinks_invoke_arn" {
  description = "Invoke ARN of the anmatlinks Lambda"
  value       = module.lambda_anmatlinks.invoke_arn
}

output "lambda_obtener_alertas_function_name" {
  description = "Name of the obtener_alertas Lambda"
  value       = module.lambda_obtener_alertas.function_name
}

output "lambda_obtener_alertas_function_arn" {
  description = "ARN of the obtener_alertas Lambda"
  value       = module.lambda_obtener_alertas.function_arn
}

output "lambda_obtener_alertas_invoke_arn" {
  description = "Invoke ARN of the obtener_alertas Lambda"
  value       = module.lambda_obtener_alertas.invoke_arn
}

output "sparticuz_chromium_layer_arn" {
  description = "Sparticuz Chromium Lambda layer attached to rag_lmbd_anmatlinks"
  value       = module.sparticuz_chromium_layer.layer_arn
}

output "anmat_s3writer_state_machine_arn" {
  description = "Step Function: anmatlinks → SQS → rag_lmbd_s3writer (async)"
  value       = module.anmat_s3_stepfunction.state_machine_arn
}

output "anmat_s3writer_state_machine_name" {
  description = "Name of the anmat → s3writer pipeline state machine"
  value       = module.anmat_s3_stepfunction.state_machine_name
}

output "boletin_oficial_state_machine_arn" {
  description = "Step Function Boletín (JSONata): bolinks → s3writer → dbwriter"
  value       = module.boletin_oficial_sfn.state_machine_arn
}

output "boletin_oficial_state_machine_name" {
  description = "Nombre del state machine (Alerts-BoletinOficialSyncronizer-<env>)"
  value       = module.boletin_oficial_sfn.state_machine_name
}

output "alert_s3writer_dlq_url" {
  description = "DLQ para mensajes que fallan tras reintentos SQS→s3writer"
  value       = aws_sqs_queue.alert_s3writer_dlq.url
}
