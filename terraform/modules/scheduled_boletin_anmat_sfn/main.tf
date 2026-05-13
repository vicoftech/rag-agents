data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/handler.py"
  output_path = "${path.module}/.build/scheduled_boletin_anmat_sfn.zip"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name_prefix}-sched-sfn-runner"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "lambda_policy" {
  statement {
    sid       = "StartBoletinAndAnmatSfn"
    actions   = ["states:StartExecution"]
    resources = [var.boletin_state_machine_arn, var.anmat_state_machine_arn]
  }
  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name_prefix}-sched-sfn-runner"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_policy.json
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name_prefix}-sched-sfn-runner"
  retention_in_days = 14
  tags              = var.tags
}

locals {
  anmat_year_env = trimspace(var.anmat_year_override) != "" ? trimspace(var.anmat_year_override) : ""
}

resource "aws_lambda_function" "runner" {
  function_name    = "${var.name_prefix}-sched-sfn-runner"
  role             = aws_iam_role.lambda.arn
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  handler          = "handler.handler"
  runtime          = var.lambda_runtime
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_size
  tags             = var.tags

  environment {
    variables = {
      BOLETIN_SFN_ARN   = var.boletin_state_machine_arn
      ANMAT_SFN_ARN     = var.anmat_state_machine_arn
      BOLETIN_TENANT_ID = var.boletin_tenant_id
      BOLETIN_AGENT_ID  = var.boletin_agent_id
      BOLETIN_SECTIONS  = var.boletin_sections
      ANMAT_TENANT_ID   = var.anmat_tenant_id
      ANMAT_AGENT_ID    = var.anmat_agent_id
      ANMAT_YEAR        = local.anmat_year_env
      SCHEDULE_TZ       = var.schedule_timezone
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler_invoke" {
  name               = "${var.name_prefix}-sched-invoke-lambda"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.runner.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "${var.name_prefix}-sched-invoke-lambda"
  role   = aws_iam_role.scheduler_invoke.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule_group" "this" {
  name = "${var.name_prefix}-boletin-anmat-daily"
  tags = var.tags
}

resource "aws_scheduler_schedule" "boletin" {
  name       = "${var.name_prefix}-boletin-daily"
  group_name = aws_scheduler_schedule_group.this.name

  flexible_time_window { mode = "OFF" }

  schedule_expression          = "cron(${var.boletin_cron_minute_hour} ? * MON-FRI *)"
  schedule_expression_timezone = var.schedule_timezone

  target {
    arn      = aws_lambda_function.runner.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    input    = jsonencode({ corpus = "boletin" })
  }
}

resource "aws_scheduler_schedule" "anmat" {
  name       = "${var.name_prefix}-anmat-daily"
  group_name = aws_scheduler_schedule_group.this.name

  flexible_time_window { mode = "OFF" }

  schedule_expression          = "cron(${var.anmat_cron_minute_hour} ? * MON-FRI *)"
  schedule_expression_timezone = var.schedule_timezone

  target {
    arn      = aws_lambda_function.runner.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    input    = jsonencode({ corpus = "anmat" })
  }
}

resource "aws_lambda_permission" "scheduler_boletin" {
  statement_id  = "AllowSchedulerBoletin"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.runner.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.boletin.arn
}

resource "aws_lambda_permission" "scheduler_anmat" {
  statement_id  = "AllowSchedulerAnmat"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.runner.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.anmat.arn
}
