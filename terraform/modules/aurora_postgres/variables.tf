variable "vpc_id" {}
variable "subnets" { type = list(string) }
variable "environment" { type = string }

variable "db_name" {}
variable "engine_version" { default = "15.3" }

variable "min_capacity" {}
variable "max_capacity" {}

variable "master_username" {
  type = string
}

variable "master_password" {
  type      = string
  sensitive = true
}

# Variables externalizadas
variable "db_port" {
  description = "Puerto para la base de datos PostgreSQL"
  type        = number
  default     = 5432
}

variable "ingress_cidr_blocks" {
  description = "Bloques CIDR permitidos para acceso a la base de datos"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "cluster_identifier" {
  description = "Identificador personalizado para el cluster"
  type        = string
  default     = null
}

variable "instance_identifier" {
  description = "Identificador personalizado para la instancia"
  type        = string
  default     = null
}

variable "aws_region" {
  description = "Región de AWS (se sobrescribe por workspace si no se especifica)"
  type        = string
  default     = null
}

