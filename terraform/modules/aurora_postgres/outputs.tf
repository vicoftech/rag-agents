output "cluster_endpoint" {
  description = "Aurora cluster endpoint"
  value       = aws_rds_cluster.this.endpoint
}

output "reader_endpoint" {
  description = "Aurora reader endpoint"
  value       = aws_rds_cluster.this.reader_endpoint
}

output "security_group_id" {
  description = "Aurora security group ID"
  value       = aws_security_group.this.id
}

output "cluster_identifier" {
  description = "Aurora cluster identifier"
  value       = aws_rds_cluster.this.cluster_identifier
}

output "port" {
  description = "Aurora cluster port"
  value       = aws_rds_cluster.this.port
}
