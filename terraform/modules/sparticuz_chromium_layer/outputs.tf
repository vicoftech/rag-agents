output "layer_arn" {
  description = "ARN of the published Sparticuz Chromium Lambda layer"
  value       = aws_lambda_layer_version.this.arn
}

output "layer_version" {
  description = "Published layer version number"
  value       = aws_lambda_layer_version.this.version
}
