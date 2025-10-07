output "vpc_id" {
  description = "ID of the created VPC."
  value       = module.network.vpc_id
}

output "eks_cluster_name" {
  description = "Name of the EKS cluster."
  value       = module.eks.cluster_name
}

output "ui_api_gateway_url" {
  description = "Invoke URL for the Nexus UI API Gateway."
  value       = aws_apigatewayv2_stage.prod.invoke_url
}

output "bronze_bucket_arn" {
  description = "ARN for the bronze (raw) S3 bucket."
  value       = aws_s3_bucket.bronze.arn
}

output "mcp_namespace" {
  description = "Kubernetes namespace hosting MCP services."
  value       = local.kubernetes_namespaces["mcp_services"]
}

output "processed_stream_name" {
  description = "Name of the processed (silver) Kinesis data stream."
  value       = aws_kinesis_stream.processed.name
}
