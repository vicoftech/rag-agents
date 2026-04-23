# Publishes the official Sparticuz Chromium Lambda layer (x86_64) via S3 staging.
# ZIP is often > 50 MB; Lambda layer source must come from S3 or container.

resource "null_resource" "download_chromium_layer_zip" {
  triggers = {
    url = var.layer_zip_url
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command     = <<-EOT
      set -euo pipefail
      OUT_DIR="${path.module}/.builds"
      OUT_FILE="${path.module}/.builds/sparticuz-chromium-layer.zip"
      mkdir -p "$OUT_DIR"
      echo "Downloading Sparticuz Chromium layer from ${var.layer_zip_url}..."
      curl -L --fail --silent --show-error "${var.layer_zip_url}" -o "$OUT_FILE"
    EOT
  }
}

resource "aws_s3_object" "layer_zip" {
  bucket = var.s3_bucket_name
  key    = "lambda-layers/sparticuz-chromium/${var.environment}/layer.zip"
  source = "${path.module}/.builds/sparticuz-chromium-layer.zip"
  # No filemd5(etag): null_resource rewrites the ZIP during apply (placeholder → full layer).

  depends_on = [null_resource.download_chromium_layer_zip]
}

resource "aws_lambda_layer_version" "this" {
  layer_name               = "rag-sparticuz-chromium-${var.environment}"
  s3_bucket                = var.s3_bucket_name
  s3_key                   = aws_s3_object.layer_zip.key
  compatible_runtimes      = ["python3.12", "python3.11", "python3.13", "nodejs20.x", "nodejs22.x"]
  compatible_architectures = ["x86_64"]

  description = "Sparticuz Chromium headless shell for Playwright (CHROMIUM_PACK_PATH=/opt/chromium)"

  depends_on = [aws_s3_object.layer_zip]
}
