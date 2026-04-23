variable "vpc_id" {
  description = "VPC donde existe el Gateway Endpoint de S3"
  type        = string
}

variable "aws_region" {
  type = string
}

variable "subnet_ids" {
  description = "Subredes cuyas tablas de rutas deben tener ruta al VPCE S3 (p. ej. subnets de Lambdas en VPC)"
  type        = list(string)
}
