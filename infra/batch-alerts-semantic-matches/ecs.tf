resource "aws_cloudwatch_log_group" "batch" {
  name              = "/ecs/${var.project_name}-${var.environment}"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "batch" {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_security_group" "batch" {
  name_prefix = "${var.project_name}-${var.environment}-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_ecs_task_definition" "batch" {
  for_each                 = local.task_families
  family                   = each.value
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_exec.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "batch"
      image     = "${aws_ecr_repository.batch.repository_url}:${var.image_tag}"
      essential = true
      user      = "1000"
      environment = [
        { name = "BATCH_CORRIDA", value = each.key },
        { name = "AWS_DEFAULT_REGION", value = var.aws_region },
        { name = "S3_DOCUMENTS_BUCKET", value = var.s3_documents_bucket },
        {
          name  = "BATCH_PARALLEL"
          value = each.key == "anmat" ? tostring(var.batch_parallel_anmat) : tostring(var.batch_parallel_boletin)
        },
        { name = "BATCH_TRACE_LAMBDA_PAYLOADS", value = var.batch_trace_lambda_payloads ? "1" : "0" },
        {
          name = "BATCH_INCLUDE_ZERO_CHUNK"
          value = (
            each.key == "anmat"
            ? (var.batch_include_zero_chunk_anmat ? "1" : "0")
            : (var.batch_include_zero_chunk_boletin ? "1" : "0")
          )
        },
        { name = "BATCH_NO_CREATED_AT_FILTER", value = var.batch_no_created_at_filter ? "1" : "0" },
        { name = "BATCH_TESTING_EMAIL", value = var.batch_testing_email },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.batch.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "${each.key}"
        }
      }
    }
  ])
}
