# Step Function: anmatlinks → Map por cada PDF → 1 mensaje SQS → rag_lmbd_s3writer (1 PDF / invocación)

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
  name               = "${var.state_machine_name}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "sfn" {
  name = "${var.state_machine_name}-sfn-policy"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = var.anmat_function_arn
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage"
        ]
        Resource = var.alert_queue_arn
      }
    ]
  })
}

resource "aws_sfn_state_machine" "anmat_to_s3" {
  name     = var.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  tags     = var.tags

  definition = jsonencode({
    Comment = "ANMAT: anmatlinks → Map(pdf_links) → 1 mensaje SQS por PDF → s3writer"
    StartAt = "RunAnmatlinks"
    States = {
      RunAnmatlinks = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.anmat_function_arn
          Payload = {
            "year.$"       = "$.year"
            "page_start.$" = "$.page_start"
            "page_end.$"   = "$.page_end"
          }
        }
        ResultPath = "$.anmatInvoke"
        Next       = "CheckAnmatSuccess"
        Retry = [
          {
            ErrorEquals = [
              "Lambda.ServiceException",
              "Lambda.AWSLambdaException",
              "Lambda.SdkClientException",
              "Lambda.TooManyRequestsException"
            ]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Failed"
          }
        ]
      }
      CheckAnmatSuccess = {
        Type = "Choice"
        Choices = [
          {
            Variable      = "$.anmatInvoke.Payload.statusCode"
            NumericEquals = 200
            Next          = "ExtractAnmatBody"
          }
        ]
        Default = "Failed"
      }
      # 1) body de anmatlinks es JSON string: lo parseamos una vez
      ExtractAnmatBody = {
        Type = "Pass"
        Parameters = {
          "data.$" = "States.StringToJson($.anmatInvoke.Payload.body)"
        }
        ResultPath = "$.anmatResponse"
        Next       = "BuildCtxForFanOut"
      }
      # 2) ctx con pdf_links[] y pdfs_collected explícitos para Choice + Map
      BuildCtxForFanOut = {
        Type = "Pass"
        Parameters = {
          "tenant_id.$"      = "$.tenant_id"
          "agent_id.$"       = "$.agent_id"
          "year.$"           = "$.year"
          "pdf_links.$"      = "$.anmatResponse.data.pdf_links"
          "pdfs_collected.$" = "$.anmatResponse.data.pdfs_collected"
        }
        ResultPath = "$.ctx"
        Next       = "HasPdfs"
      }
      HasPdfs = {
        Type = "Choice"
        Choices = [
          {
            Variable           = "$.ctx.pdfs_collected"
            NumericGreaterThan = 0
            Next               = "FanOutPdfs"
          }
        ]
        Default = "NoPdfsDone"
      }
      FanOutPdfs = {
        Type           = "Map"
        ItemsPath      = "$.ctx.pdf_links"
        MaxConcurrency = var.map_max_concurrency
        ItemSelector = {
          "tenant_id.$" = "$.ctx.tenant_id"
          "agent_id.$"  = "$.ctx.agent_id"
          "pdf.$"       = "$$.Map.Item.Value"
          "mode"        = "single_pdf"
        }
        Iterator = {
          StartAt = "SendPdfToQueue"
          States = {
            SendPdfToQueue = {
              Type     = "Task"
              Resource = "arn:aws:states:::sqs:sendMessage"
              Parameters = {
                QueueUrl        = var.alert_queue_url
                "MessageBody.$" = "States.JsonToString($)"
              }
              End = true
              Retry = [
                {
                  ErrorEquals = [
                    "SQS.SdkClientException",
                    "States.TaskFailed"
                  ]
                  IntervalSeconds = 2
                  MaxAttempts     = 3
                  BackoffRate     = 2
                }
              ]
            }
          }
        }
        Next = "AllQueued"
      }
      AllQueued = {
        Type = "Succeed"
      }
      NoPdfsDone = {
        Type = "Succeed"
      }
      Failed = {
        Type  = "Fail"
        Error = "AnmatToS3PipelineFailed"
        Cause = "anmatlinks falló, devolvió no-200, o error en Map/SQS"
      }
    }
  })
}

resource "aws_lambda_permission" "sfn_invoke_anmat" {
  statement_id  = "AllowExecutionFromStepFunctions-${var.state_machine_name}"
  action        = "lambda:InvokeFunction"
  function_name = var.anmat_function_name
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.anmat_to_s3.arn
}
