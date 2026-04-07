variable "aws_region" {
  type        = string
  description = "Región AWS"
  default     = "us-east-1"
}

variable "aws_profile" {
  type        = string
  description = "Perfil AWS CLI (vacío = cadena de credenciales por defecto)"
  default     = "asap_dev"
}

variable "state_bucket_name" {
  type        = string
  description = "Nombre globalmente único del bucket de estado"
  default     = "rag-agents-terraform-state-615216531593"
}

variable "lock_table_name" {
  type        = string
  description = "Nombre de la tabla DynamoDB para bloqueo de estado"
  default     = "rag-agents-terraform-locks"
}
