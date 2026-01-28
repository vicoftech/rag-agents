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

output "master_username" {
  description = "Master username for the database"
  value       = aws_rds_cluster.this.master_username
}

output "master_password" {
  description = "Master password for the database"
  value       = aws_rds_cluster.this.master_password
  sensitive   = true
}

output "database_name" {
  description = "Name of the default database"
  value       = aws_rds_cluster.this.database_name
}

output "connection_string" {
  description = "Connection string for psql (password excluded for security)"
  value       = "psql -h ${aws_rds_cluster.this.endpoint} -U ${aws_rds_cluster.this.master_username} -d ${aws_rds_cluster.this.database_name} -p ${aws_rds_cluster.this.port}"
}
