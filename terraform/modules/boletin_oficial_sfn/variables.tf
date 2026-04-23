variable "state_machine_name" {
  description = "Nombre del state machine (p. ej. Alerts-BoletinOficialSyncronizer-prod)"
  type        = string
}

variable "bolinks_function_arn" {
  description = "ARN de rag_lmbd_bolinks (sin :$LATEST; la definición ASL añade :$LATEST)"
  type        = string
}

variable "s3writer_function_arn" {
  type = string
}

variable "dbwriter_function_arn" {
  type = string
}

variable "bolinks_function_name" {
  description = "Nombre lógico de la Lambda (para permisos)"
  type        = string
}

variable "s3writer_function_name" {
  type = string
}

variable "dbwriter_function_name" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
