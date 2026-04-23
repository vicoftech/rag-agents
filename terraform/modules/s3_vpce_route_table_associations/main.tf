# Asocia el VPC Endpoint Gateway de S3 existente a las tablas de rutas de las subredes indicadas,
# solo para las tablas que aún no estén asociadas (idempotente; evita duplicados en AWS).

data "aws_vpc_endpoint" "s3_gateway" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "service-name"
    values = ["com.amazonaws.${var.aws_region}.s3"]
  }
  filter {
    name   = "vpc-endpoint-type"
    values = ["Gateway"]
  }
}

data "aws_route_table" "subnet" {
  for_each  = toset(var.subnet_ids)
  subnet_id = each.value
}

locals {
  route_tables_from_subnets = toset([
    for s in var.subnet_ids : data.aws_route_table.subnet[s].id
  ])
  route_tables_on_endpoint = toset(data.aws_vpc_endpoint.s3_gateway.route_table_ids)
  # Tablas de rutas que usan las subnets pero aún no están en el endpoint
  missing_route_table_ids = setsubtract(
    local.route_tables_from_subnets,
    local.route_tables_on_endpoint
  )
}

resource "aws_vpc_endpoint_route_table_association" "s3_gateway" {
  for_each = local.missing_route_table_ids

  vpc_endpoint_id = data.aws_vpc_endpoint.s3_gateway.id
  route_table_id  = each.value
}
