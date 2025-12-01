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

