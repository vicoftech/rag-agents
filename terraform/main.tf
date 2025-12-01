terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.20.0"
    }
  }
  required_version = ">= 1.3.0"
}



provider "aws" {
  region  = var.region
  profile = var.aws_profile
}

locals {
  env = terraform.workspace
}

module "aurora" {
  source = "./modules/aurora_postgres"

  vpc_id      = var.vpc_id
  subnets     = var.subnets
  environment = local.env

  db_name       = "ragdb_${local.env}"

  min_capacity = 0.5
  max_capacity = 4

  master_username = var.master_username
  master_password = var.master_password
  engine_version = var.engine_version
}
