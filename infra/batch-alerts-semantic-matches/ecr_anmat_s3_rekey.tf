# ECR para batch/anmat-s3-rekey (CI: .github/workflows/batch-anmat-s3-rekey-docker.yml)

resource "aws_ecr_repository" "anmat_s3_rekey" {
  name                 = "rag-batch-anmat-s3-rekey-${var.environment}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "anmat_s3_rekey" {
  repository = aws_ecr_repository.anmat_s3_rekey.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Conservar sólo las últimas 15 imágenes"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 15
      }
      action = {
        type = "expire"
      }
    }]
  })
}
