# --- ECS task execution (pull ECR + logs) ---
resource "aws_iam_role" "ecs_exec" {
  name = "${var.project_name}-exec-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_exec_managed" {
  role       = aws_iam_role.ecs_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- ECS task (script: Lambda + SQS) ---
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

locals {
  lambda_obtener = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:rag_lmbd_obtener_alertas-${var.lambda_env_suffix}"
  lambda_query   = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:rag_lmbd_query-${var.lambda_env_suffix}"
  sqs_email      = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:email-sender-record-email-processor-${var.sqs_env_suffix}"
  sqs_alerts     = "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rag-alert-creation-${var.sqs_env_suffix}"
}

resource "aws_iam_role_policy" "ecs_task_batch" {
  name = "alerts-semantic-matches"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeQueryLambdas"
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          local.lambda_obtener,
          "${local.lambda_obtener}:*",
          local.lambda_query,
          "${local.lambda_query}:*",
        ]
      },
      {
        Sid    = "PublishQueues"
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:GetQueueUrl"
        ]
        Resource = [
          local.sqs_email,
          local.sqs_alerts
        ]
      }
    ]
  })
}

# --- EventBridge Scheduler → ecs:RunTask ---
resource "aws_iam_role" "scheduler" {
  name = "${var.project_name}-scheduler-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "scheduler.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_run_task" {
  name = "run-ecs-task"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:RunTask"
        ]
        Resource = local.ecs_run_task_resources
      },
      {
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          aws_iam_role.ecs_exec.arn,
          aws_iam_role.ecs_task.arn
        ]
      }
    ]
  })
}
