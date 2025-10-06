data "archive_file" "lambda_auth" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/auth"
  output_path = "${path.module}/../lambda/dist/auth.zip"
}

resource "aws_lambda_function" "auth" {
  function_name = "${local.name_prefix}-auth"
  role          = aws_iam_role.lambda_auth.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.lambda_auth.output_path
  source_code_hash = data.archive_file.lambda_auth.output_base64sha256

  environment {
    variables = {
      PROJECT                = var.project
      TOKEN_ROLE_ARN         = aws_iam_role.kinesis_bearer.arn
      CLIENT_DATA_STREAM     = aws_kinesis_stream.client_intake.name
      CLIENT_VIDEO_STREAM    = aws_kinesis_video_stream.client_telemetry.name
      CLIENT_FIREHOSE_STREAM = aws_kinesis_firehose_delivery_stream.client_lake_ingest.name
    }
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "lambda_auth" {
  name              = "/aws/lambda/${aws_lambda_function.auth.function_name}"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_apigatewayv2_api" "nexus" {
  name          = "${local.name_prefix}-ui"
  protocol_type = "HTTP"
  tags          = local.common_tags
}

resource "aws_apigatewayv2_integration" "auth" {
  api_id           = aws_apigatewayv2_api.nexus.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.auth.invoke_arn
  integration_method = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "auth" {
  api_id    = aws_apigatewayv2_api.nexus.id
  route_key = "POST /auth"
  target    = "integrations/${aws_apigatewayv2_integration.auth.id}"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id = aws_apigatewayv2_api.nexus.id
  name   = "prod"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
    format = jsonencode({
      requestId = "$context.requestId",
      sourceIp  = "$context.identity.sourceIp",
      routeKey  = "$context.routeKey",
      status    = "$context.status"
    })
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${local.name_prefix}-ui"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_lambda_permission" "auth_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.nexus.execution_arn}/*/*"
}

resource "aws_apigatewayv2_domain_name" "ui" {
  count = length(var.ui_domain_name) > 0 ? 1 : 0

  domain_name = var.ui_domain_name

  domain_name_configuration {
    certificate_arn = "REPLACE_WITH_ACM_CERT_ARN"
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_api_mapping" "ui" {
  count = length(var.ui_domain_name) > 0 ? 1 : 0

  api_id      = aws_apigatewayv2_api.nexus.id
  domain_name = aws_apigatewayv2_domain_name.ui[0].id
  stage       = aws_apigatewayv2_stage.prod.id
}
