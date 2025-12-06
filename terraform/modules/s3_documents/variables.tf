variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string
}

variable "enable_lifecycle" {
  description = "Enable lifecycle rules for cost optimization"
  type        = bool
  default     = true
}

variable "enable_cors" {
  description = "Enable CORS configuration"
  type        = bool
  default     = false
}

variable "cors_allowed_origins" {
  description = "Allowed origins for CORS"
  type        = list(string)
  default     = ["*"]
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
