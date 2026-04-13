variable "environment" {
  description = "Deployment environment name (e.g. qa, dev)"
  type        = string
}

variable "s3_bucket_name" {
  description = "S3 bucket used to stage the layer ZIP (must allow Terraform to upload)"
  type        = string
}

variable "layer_zip_url" {
  description = "Official Sparticuz Chromium Lambda layer ZIP (x86_64)"
  type        = string
  default     = "https://github.com/Sparticuz/chromium/releases/download/v143.0.4/chromium-v143.0.4-layer.x64.zip"
}
