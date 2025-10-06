resource "aws_s3_bucket" "bronze" {
  bucket        = "${local.name_prefix}-bronze-${var.region}"
  force_destroy = true

  tags = merge(local.common_tags, { MedallionTier = "bronze" })
}

resource "aws_s3_bucket_versioning" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "silver" {
  bucket        = "${local.name_prefix}-silver-${var.region}"
  force_destroy = true
  tags          = merge(local.common_tags, { MedallionTier = "silver" })
}

resource "aws_s3_bucket_versioning" "silver" {
  bucket = aws_s3_bucket.silver.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "silver" {
  bucket = aws_s3_bucket.silver.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "gold" {
  bucket        = "${local.name_prefix}-gold-${var.region}"
  force_destroy = true
  tags          = merge(local.common_tags, { MedallionTier = "gold" })
}

resource "aws_s3_bucket_versioning" "gold" {
  bucket = aws_s3_bucket.gold.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "gold" {
  bucket = aws_s3_bucket.gold.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "vibranium" {
  bucket        = "${local.name_prefix}-vibranium-${var.region}"
  force_destroy = true
  tags          = merge(local.common_tags, { MedallionTier = "vibranium" })
}

resource "aws_s3_bucket_versioning" "vibranium" {
  bucket = aws_s3_bucket.vibranium.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "vibranium" {
  bucket = aws_s3_bucket.vibranium.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

locals {
  medallion_bucket_arns = {
    bronze    = aws_s3_bucket.bronze.arn
    silver    = aws_s3_bucket.silver.arn
    gold      = aws_s3_bucket.gold.arn
    vibranium = aws_s3_bucket.vibranium.arn
  }

  firehose_log_groups = {
    primary = "/aws/kinesisfirehose/${local.name_prefix}-firehose"
    client  = "/aws/kinesisfirehose/${local.name_prefix}-client-firehose"
  }
}

resource "aws_kinesis_stream" "intake" {
  name             = "${local.name_prefix}-intake"
  shard_count      = 2
  retention_period = 48

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = local.common_tags
}

resource "aws_kinesis_stream" "client_intake" {
  name             = "${local.name_prefix}-client-intake"
  shard_count      = 1
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = local.common_tags
}

resource "aws_kinesis_video_stream" "telemetry" {
  name                   = "${local.name_prefix}-telemetry"
  data_retention_in_hours = 24
  media_type             = "video/h264"

  tags = local.common_tags
}

resource "aws_kinesis_video_stream" "client_telemetry" {
  name                   = "${local.name_prefix}-client-telemetry"
  data_retention_in_hours = 12
  media_type             = "video/h264"

  tags = local.common_tags
}

resource "aws_iam_role" "firehose" {
  name               = "${local.name_prefix}-firehose"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "firehose.amazonaws.com"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "sts:ExternalId" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "firehose" {
  name = "${local.name_prefix}-firehose"
  role = aws_iam_role.firehose.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.bronze.arn,
          "${aws_s3_bucket.bronze.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:PutLogEvents"
        ]
        Resource = [
          "arn:${data.aws_partition.current.partition}:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:${local.firehose_log_groups.primary}:*",
          "arn:${data.aws_partition.current.partition}:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:${local.firehose_log_groups.client}:*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kinesis:DescribeStream",
          "kinesis:GetShardIterator",
          "kinesis:GetRecords"
        ]
        Resource = [
          aws_kinesis_stream.intake.arn,
          aws_kinesis_stream.client_intake.arn
        ]
      }
    ]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "lake_ingest" {
  name        = "${local.name_prefix}-to-lake"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.intake.arn
    role_arn           = aws_iam_role.firehose.arn
  }

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.bronze.arn
    compression_format  = "GZIP"
    buffering_interval  = 300
    buffering_size      = 128
    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = local.firehose_log_groups.primary
      log_stream_name = "S3Delivery"
    }
  }

  tags = local.common_tags
}

resource "aws_kinesis_firehose_delivery_stream" "client_lake_ingest" {
  name        = "${local.name_prefix}-client-to-lake"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.client_intake.arn
    role_arn           = aws_iam_role.firehose.arn
  }

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.bronze.arn
    prefix              = "client/"
    compression_format  = "GZIP"
    buffering_interval  = 300
    buffering_size      = 64
    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = local.firehose_log_groups.client
      log_stream_name = "S3Delivery"
    }
  }

  tags = merge(local.common_tags, { DataTier = "client" })
}

resource "aws_cloudwatch_log_group" "firehose" {
  name              = local.firehose_log_groups.primary
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "firehose_client" {
  name              = local.firehose_log_groups.client
  retention_in_days = 14
  tags              = merge(local.common_tags, { DataTier = "client" })
}

resource "aws_lakeformation_data_lake_settings" "this" {
  administrators = length(var.lakeformation_admins) > 0 ? var.lakeformation_admins : [data.aws_caller_identity.current.arn]
}

resource "aws_lakeformation_resource" "medallion" {
  for_each = local.medallion_bucket_arns

  arn = each.value
}

resource "aws_lakeformation_permissions" "medallion_admin" {
  for_each = local.medallion_bucket_arns

  principal   = length(var.lakeformation_admins) > 0 ? var.lakeformation_admins[0] : data.aws_caller_identity.current.arn
  permissions = ["DATA_LOCATION_ACCESS"]
  data_location {
    arn = each.value
  }
}
