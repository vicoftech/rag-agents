variable "environment" {
  description = "Deployment environment (e.g., dev, prod)"
  type        = string
}

variable "region" {
  description = "AWS region to deploy resources"
  type        = string
}


variable "aws_profile" {
  description = "AWS CLI named profile to use for credentials"
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "subnets" {
  type = list(string)
}

variable "master_username" {
  type = string
}

variable "master_password" {
  type      = string
  sensitive = true
}

variable "engine_version" {
  type      = string
  sensitive = true
}
