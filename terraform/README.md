# Terraform Stack

This module provisions the baseline AWS footprint required by Nexus.

## Components

- **Networking**: VPC with public/private subnets, NAT gateway, DNS support via `terraform-aws-modules/vpc`.
- **EKS**: Managed control plane, general and MCP node groups, optional Karpenter (enabled via `enable_karpenter`).
- **IAM**: IRSA roles for the agent core and AWS MCP service (Bedrock, Kinesis, Glue, Lake access), Lambda execution role, Firehose service role, and a bearer-token role assumed by Lambda to mint short-lived Kinesis credentials for clients.
- **Data Platform**: Primary and client Kinesis Data Streams, a processed silver stream, paired Kinesis Video Streams, paired Kinesis Firehose delivery streams into the bronze bucket (client data lands under the `client/` prefix), versioned S3 buckets for medallion layers, Lake Formation registration and permissions.
- **Edge & Auth**: Python Lambda packaged via `archive_file`, HTTP API Gateway with logging, optional custom domain mapping, and STS-backed bearer token issuance for producers/consumers.
- **Autoscaling**: Helm release installs KEDA so workloads can scale on external metrics (e.g., Kinesis lag).

## Usage

```bash
terraform init
terraform plan -var='environment=dev' -var='lakeformation_admins=["arn:aws:iam::123456789012:role/Admin"]'
terraform apply
```

### Variables

- `project` / `environment` control naming and tagging.
- `lakeformation_admins` should list administrator IAM principals.
- `agent_bedrock_models` whitelists Bedrock models for the agent and AWS MCP services.
- `enable_karpenter` toggles managed autoscaling support.
- `ui_domain_name` optionally binds an API custom domain (requires ACM cert ARN in `api.tf`).

### Outputs

- `vpc_id`
- `eks_cluster_name`
- `ui_api_gateway_url`
- `bronze_bucket_arn`
- `processed_stream_name`
- `mcp_namespace`

> IAM role ARNs (agent IRSA, AWS MCP IRSA, bearer-token role) are available via the Terraform state/output and should be recorded during deployment.

## Extending

- Create additional IAM roles for domain-specific MCP workloads.
- Attach Lake Formation LF-Tags to enforce data-tier access policies.
- Add CloudFront and static hosting for the UI if an external endpoint is required.
- Introduce additional Kinesis channels or customer-specific prefixes, duplicating the client pattern.
