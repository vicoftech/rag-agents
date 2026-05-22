variable "name_prefix" {
  description = "Prefijo para nombres de recursos (ej. rag-prod-913)"
  type        = string
}

variable "tags" {
  description = "Tags comunes"
  type        = map(string)
  default     = {}
}

variable "boletin_state_machine_arn" {
  description = "ARN principal del SFN Boletín (p. ej. Alerts-BoletinOficialSyncronizer heredado sin -prod)"
  type        = string
}

variable "boletin_state_machine_arns_extra" {
  description = "ARNs adicionales con states:StartExecution (p. ej. -prod o -async-prod si coexisten)"
  type        = list(string)
  default     = []
}

variable "anmat_state_machine_arn" {
  description = "ARN principal del SFN ANMAT (p. ej. rag-anmat-to-s3writer-prod)"
  type        = string
}

variable "anmat_state_machine_arns_extra" {
  description = "ARNs adicionales ANMAT con states:StartExecution (aliases/entornos legacy)"
  type        = list(string)
  default     = []
}

variable "boletin_tenant_id" {
  type    = string
  default = "tenant_boletin"
}

variable "boletin_agent_id" {
  type        = string
  description = "UUID agente RAG boletín"
}

variable "anmat_tenant_id" {
  type    = string
  default = "anmat"
}

variable "anmat_agent_id" {
  type        = string
  description = "UUID agente RAG ANMAT"
}

variable "schedule_timezone" {
  description = "IANA TZ para interpretar horas 9:00 y 9:30 (ej. America/Argentina/Buenos_Aires)"
  type        = string
  default     = "America/Argentina/Buenos_Aires"
}

variable "boletin_cron_minute_hour" {
  description = "Minuto y hora locales (resto: ? * MON-FRI *). Ej: \"30 11\" = 11:30 lun–vie"
  type        = string
  default     = "30 11"
}

variable "anmat_cron_minute_hour" {
  description = "Minuto y hora locales ANMAT ingesta (lun–vie). Ej: \"0 11\" = 11:00"
  type        = string
  default     = "0 11"
}

variable "anmat_year_override" {
  description = "Vacío = año civil actual en schedule_timezone; si no vacío fuerza ese año (string)"
  type        = string
  default     = ""
}

variable "boletin_sections" {
  description = "Secciones separadas por coma (sólo primera, segunda, tercera — I a III del BO)"
  type        = string
  default     = "primera,segunda,tercera"
}

variable "lambda_runtime" {
  type    = string
  default = "python3.12"
}

variable "lambda_timeout_seconds" {
  type    = number
  default = 120
}

variable "lambda_memory_size" {
  type    = number
  default = 128
}
