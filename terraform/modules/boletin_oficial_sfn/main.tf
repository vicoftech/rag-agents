# Step Function: Boletín (bolinks → s3writer → dbwriter) con ASL2 / JSONata

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.state_machine_name}-sfn-exec"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "sfn" {
  name = "invoke-bolinks-s3writer-dbwriter"
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [for a in [var.bolinks_function_arn, var.s3writer_function_arn, var.dbwriter_function_arn] : "${a}:*"]
      }
    ]
  })
}

resource "aws_sfn_state_machine" "boletin" {
  name     = var.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  tags     = var.tags

  definition = templatefile("${path.module}/boletin_sfn.asl.tftpl", {
    bolinks_qualified  = "${var.bolinks_function_arn}:$LATEST"
    s3writer_qualified = "${var.s3writer_function_arn}:$LATEST"
    dbwriter_qualified = "${var.dbwriter_function_arn}:$LATEST"
  })
}

resource "aws_lambda_permission" "sfn_bolinks" {
  statement_id  = "AllowStepFunctions-boletin-oficial-${var.state_machine_name}"
  action        = "lambda:InvokeFunction"
  function_name = var.bolinks_function_name
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.boletin.arn
}

resource "aws_lambda_permission" "sfn_s3writer" {
  statement_id  = "AllowStepFunctions-boletin-s3w-${var.state_machine_name}"
  action        = "lambda:InvokeFunction"
  function_name = var.s3writer_function_name
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.boletin.arn
}

resource "aws_lambda_permission" "sfn_dbwriter" {
  statement_id  = "AllowStepFunctions-boletin-dbw-${var.state_machine_name}"
  action        = "lambda:InvokeFunction"
  function_name = var.dbwriter_function_name
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.boletin.arn
}
