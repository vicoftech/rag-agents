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
  description = "ARN del SFN Alerts-BoletinOficialSyncronizer (prod/qa)"
  type        = string
}

variable "anmat_state_machine_arn" {
  description = "ARN del SFN rag-anmat-to-s3writer (prod/qa)"
  type        = string
}

variable "boletin_tenant_id" {
  type    = string
  default = "boletin"
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
  description = "Minuto y hora locales (resto: ? * MON-FRI *). Ej: \"0 9\" = 09:00 lun–vie"
  type        = string
  default     = "0 9"
}

variable "anmat_cron_minute_hour" {
  description = "Minuto y hora locales ANMAT (lun–vie). Ej: \"30 9\" = 09:30"
  type        = string
  default     = "30 9"
}

variable "anmat_year_override" {
  description = "Vacío = año civil actual en schedule_timezone; si no vacío fuerza ese año (string)"
  type        = string
  default     = ""
}

variable "boletin_sections" {
  description = "Secciones separadas por coma (orden bolinks)"
  type        = string
  default     = "primera,segunda,tercera,cuarta"
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
