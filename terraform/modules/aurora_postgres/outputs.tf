output "cluster_endpoint" {
  description = "Hostname del writer (lectura/escritura). En Aurora, cluster.endpoint ES el host writer."
  value       = aws_rds_cluster.this.endpoint
}

output "writer_endpoint" {
  description = "Alias del host writer; mismo valor que cluster_endpoint."
  value       = aws_rds_cluster.this.endpoint
}

output "reader_endpoint" {
  description = "Hostname del reader endpoint (solo lectura, load-balanced sobre réplicas)."
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
