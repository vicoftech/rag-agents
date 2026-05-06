variable "api_name" {
  description = "Name of the API Gateway"
  type        = string
}

variable "api_description" {
  description = "Description of the API Gateway"
  type        = string
  default     = "API Gateway for RAG Query with JWT authentication"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the Lambda function (for permissions)"
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Invoke ARN of the Lambda function (for API Gateway integration)"
  type        = string
}

variable "dispatcher_lambda_function_name" {
  description = "Nombre de la Lambda que despacha POST/GET async (vacío = POST /query va al worker síncrono)"
  type        = string
  default     = ""
}

variable "dispatcher_lambda_invoke_arn" {
  description = "Invoke ARN del dispatcher para API Gateway HTTP API"
  type        = string
  default     = ""
}

variable "enable_query_dispatcher" {
  description = "Si true, rutas POST/GET /query/async usan integrations del dispatcher (count estable; debe coincidir con enable_async_* en root)."
  type        = bool
  default     = false
}

variable "cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID"
  type        = string
}

variable "cognito_endpoint" {
  description = "Cognito issuer endpoint (https://cognito-idp.<region>.amazonaws.com/<user_pool_id>)"
  type        = string
}

variable "cors_allowed_origins" {
  description = "Allowed origins for CORS"
  type        = list(string)
  default     = ["*"]
}

variable "cors_allowed_methods" {
  description = "Allowed methods for CORS"
  type        = list(string)
  default     = ["GET", "POST", "OPTIONS"]
}

variable "cors_allowed_headers" {
  description = "Allowed headers for CORS"
  type        = list(string)
  default     = ["*"]
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
