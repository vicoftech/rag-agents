output "state_bucket_name" {
  value       = aws_s3_bucket.tfstate.id
  description = "Bucket para terraform backend"
}

output "lock_table_name" {
  value       = aws_dynamodb_table.tf_locks.name
  description = "Tabla DynamoDB para locks"
}

output "backend_hcl_snippet" {
  value = <<-EOT
    bucket         = "${aws_s3_bucket.tfstate.id}"
    key            = "rag-agents/terraform.tfstate"
    region         = "${var.aws_region}"
    encrypt        = true
    dynamodb_table = "${aws_dynamodb_table.tf_locks.name}"
    profile        = "${var.aws_profile}"
  EOT
}
