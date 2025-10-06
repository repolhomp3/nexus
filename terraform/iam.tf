data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  oidc_provider = replace(
    module.eks.oidc_provider_arn,
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/",
    ""
  )
  service_account_subjects = {
    agent_core = "system:serviceaccount:${local.kubernetes_namespaces["agent_core"]}:agent-orchestrator"
    aws_mcp    = "system:serviceaccount:${local.kubernetes_namespaces["mcp_services"]}:aws-mcp"
  }
}

resource "aws_iam_role" "agent_irsa" {
  name               = "${local.name_prefix}-agent"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = module.eks.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_provider}:sub" = local.service_account_subjects["agent_core"]
          }
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "agent_bedrock" {
  name        = "${local.name_prefix}-agent-bedrock"
  description = "Allow the Nexus agent to run inference against approved Bedrock models."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:ListFoundationModels"
        ]
        Resource = [for model in var.agent_bedrock_models : "arn:${data.aws_partition.current.partition}:bedrock:${var.region}::foundation-model/${model}"]
      }
    ]
  })
}

resource "aws_iam_policy" "agent_data_access" {
  name        = "${local.name_prefix}-agent-data"
  description = "Allow the Nexus agent to interact with Kinesis, Firehose, and S3 lake tiers."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:DescribeStream",
          "kinesis:GetShardIterator",
          "kinesis:GetRecords",
          "kinesis:PutRecord",
          "kinesis:PutRecords"
        ]
        Resource = [
          aws_kinesis_stream.intake.arn,
          aws_kinesis_stream.client_intake.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kinesisvideo:*"
        ]
        Resource = [
          "${aws_kinesis_video_stream.telemetry.arn}*",
          "${aws_kinesis_video_stream.client_telemetry.arn}*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "firehose:DescribeDeliveryStream",
          "firehose:PutRecord",
          "firehose:PutRecordBatch"
        ]
        Resource = [
          aws_kinesis_firehose_delivery_stream.lake_ingest.arn,
          aws_kinesis_firehose_delivery_stream.client_lake_ingest.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = concat(
          [
            aws_s3_bucket.bronze.arn,
            aws_s3_bucket.silver.arn,
            aws_s3_bucket.gold.arn,
            aws_s3_bucket.vibranium.arn
          ],
          [
            "${aws_s3_bucket.bronze.arn}/*",
            "${aws_s3_bucket.silver.arn}/*",
            "${aws_s3_bucket.gold.arn}/*",
            "${aws_s3_bucket.vibranium.arn}/*"
          ]
        )
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_attach_bedrock" {
  role       = aws_iam_role.agent_irsa.name
  policy_arn = aws_iam_policy.agent_bedrock.arn
}

resource "aws_iam_role_policy_attachment" "agent_attach_data" {
  role       = aws_iam_role.agent_irsa.name
  policy_arn = aws_iam_policy.agent_data_access.arn
}

resource "aws_iam_role" "aws_mcp_irsa" {
  name               = "${local.name_prefix}-aws-mcp"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = module.eks.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.oidc_provider}:sub" = local.service_account_subjects["aws_mcp"]
          }
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "aws_mcp_access" {
  name        = "${local.name_prefix}-aws-mcp"
  description = "Allow the AWS MCP service to interact with S3, Glue, and Bedrock."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:ListAllMyBuckets"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = [
          aws_s3_bucket.bronze.arn,
          aws_s3_bucket.silver.arn,
          aws_s3_bucket.gold.arn,
          aws_s3_bucket.vibranium.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:ListFoundationModels"
        ]
        Resource = [for model in var.agent_bedrock_models : "arn:${data.aws_partition.current.partition}:bedrock:${var.region}::foundation-model/${model}"]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetJobs",
          "glue:StartJobRun",
          "glue:GetJobRun"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "aws_mcp_attach" {
  role       = aws_iam_role.aws_mcp_irsa.name
  policy_arn = aws_iam_policy.aws_mcp_access.arn
}

resource "aws_iam_role" "lambda_auth" {
  name               = "${local.name_prefix}-lambda-auth"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role" "kinesis_bearer" {
  name               = "${local.name_prefix}-kinesis-bearer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.lambda_auth.arn
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "kinesis_bearer" {
  name = "${local.name_prefix}-kinesis-bearer"
  role = aws_iam_role.kinesis_bearer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:GetShardIterator",
          "kinesis:GetRecords",
          "kinesis:ListShards",
          "kinesis:PutRecord",
          "kinesis:PutRecords"
        ]
        Resource = aws_kinesis_stream.client_intake.arn
      },
      {
        Effect = "Allow"
        Action = [
          "kinesisvideo:ConnectAsProducer",
          "kinesisvideo:ConnectAsViewer",
          "kinesisvideo:DescribeStream",
          "kinesisvideo:GetDataEndpoint",
          "kinesisvideo:GetMedia",
          "kinesisvideo:ListFragments",
          "kinesisvideo:GetClip",
          "kinesisvideo:GetImages",
          "kinesisvideo:PutMedia"
        ]
        Resource = "${aws_kinesis_video_stream.client_telemetry.arn}*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_auth.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_custom" {
  name = "${local.name_prefix}-lambda-custom"
  role = aws_iam_role.lambda_auth.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "sts:AssumeRole"
        ]
        Resource = aws_iam_role.kinesis_bearer.arn
      }
    ]
  })
}
