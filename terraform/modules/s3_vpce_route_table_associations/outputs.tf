output "s3_gateway_vpc_endpoint_id" {
  value       = data.aws_vpc_endpoint.s3_gateway.id
  description = "ID del VPC Endpoint Gateway S3"
}

output "route_table_ids_associated" {
  value       = keys(aws_vpc_endpoint_route_table_association.s3_gateway)
  description = "Route table IDs a las que se añadió asociación en esta aplicación"
}

output "missing_route_table_ids_resolved" {
  value       = sort(tolist(local.missing_route_table_ids))
  description = "Conjunto calculado de RTB que faltaban antes del apply"
}
