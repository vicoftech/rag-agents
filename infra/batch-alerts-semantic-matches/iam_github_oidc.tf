# Credenciales para GitHub Actions (solo push ECR batch). Ver output github_actions_ecr_role_arn.

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com",
  ]

  thumbprint_list = [
    # GitHub’s CA (documentación oficial OIDC ⇄ AWS)
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

resource "aws_iam_role" "github_ecr_batch" {
  name = "${var.project_name}-github-ecr-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo_full}:*"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ecr_push" {
  name = "ecr-push-batch-image"
  role = aws_iam_role.github_ecr_batch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrAuthToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "EcrPushRepo"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
        ]
        Resource = [
          aws_ecr_repository.batch.arn,
          aws_ecr_repository.anmat_s3_rekey.arn,
        ]
      }
    ]
  })
}

# Permisos para que GitHub Actions actualice el código de las Lambdas rag_lmbd_*.
# Policy separada; no tocar github_ecr_push ni el rol.
resource "aws_iam_role_policy" "github_lambda_deploy" {
  name = "lambda-deploy-rag-lmbd"
  role = aws_iam_role.github_ecr_batch.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaUpdateCode"
        Effect = "Allow"
        Action = [
          "lambda:UpdateFunctionCode",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:rag_lmbd_*"
      }
    ]
  })
}
