# Project Nexus Deployment Guide

This guide provides step-by-step instructions to deploy Project Nexus from source. Follow the steps sequentially; optional tasks are marked accordingly.

---

## 1. Prerequisites

### 1.1 Local Tooling
Install and verify the following tools on your workstation or CI runner:
- [Terraform](https://developer.hashicorp.com/terraform/downloads) ≥ 1.5.0 (`terraform -version`)
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (`aws --version`)
- [kubectl](https://kubernetes.io/docs/tasks/tools/) ≥ 1.29 (`kubectl version --client`)
- [Docker](https://docs.docker.com/engine/install/) with access to build/push images (`docker --version`)
- [Helm](https://helm.sh/docs/intro/install/) (optional, for future extensions)
- Python 3.11+ (for local Lambda testing) *(optional)*

### 1.2 AWS Account Readiness
- AWS account with permissions to create IAM roles, VPC networking, EKS clusters, Kinesis, S3, Lake Formation, Lambda, and API Gateway resources.
- An [IAM identity](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users.html) configured for the AWS CLI (profile `nexus` assumed below). Run `aws sts get-caller-identity --profile nexus` to verify access.
- If using a custom domain, provision an ACM certificate in `us-west-2` and note the ARN.

### 1.3 Repository Setup
Clone the repository (already present in `/Users/karl/nexus`). Ensure the working tree is clean and that placeholders (account IDs, image names) will be updated before final deploy.

---

## 2. Configure Terraform Variables

Navigate to the Terraform directory:
```bash
cd terraform
```

Define variables via `terraform.tfvars`, CLI flags, or environment variables. Typical overrides:
```hcl
project             = "nexus"
environment         = "dev"
region              = "us-west-2"
lakeformation_admins = ["arn:aws:iam::123456789012:role/Admin"]
agent_bedrock_models = [
  "anthropic.claude-3-sonnet-20240229-v1:0",
  "amazon.titan-text-express-v1"
]
ui_domain_name      = "" # leave blank to skip custom domain
```

> **Tip:** Update `lakeformation_admins` with real IAM principals, and ensure `agent_bedrock_models` align with models enabled in your AWS account.

---

## 3. Provision AWS Infrastructure with Terraform

1. **Initialize providers/modules**
   ```bash
   terraform init
   ```

2. **Review the plan**
   ```bash
   terraform plan -var='environment=dev' -var='region=us-west-2' -out=tfplan
   ```
   Inspect the output for unexpected changes.

3. **Apply the infrastructure**
   ```bash
   terraform apply tfplan
   ```
   (Or run `terraform apply` interactively.)

4. **Record key outputs**
   ```bash
   terraform output
   ```
   Capture:
   - `eks_cluster_name`
   - `ui_api_gateway_url`
   - IAM role ARNs: `aws_iam_role.agent_irsa`, `aws_iam_role.aws_mcp_irsa`, and `aws_iam_role.kinesis_bearer` (from state or console)

5. **(Optional) Configure kubeconfig**
   ```bash
   aws eks update-kubeconfig \
     --name $(terraform output -raw eks_cluster_name) \
     --region $(terraform output -raw region) \
     --profile nexus
   ```

---

## 4. Build and Push Container Images

Terraform does not build application images; use Docker to package services. Replace `<account-id>` with your AWS account number.

1. **Authenticate to Amazon ECR**
   ```bash
   aws ecr get-login-password --region us-west-2 --profile nexus | \
     docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-west-2.amazonaws.com
   ```

2. **Create ECR repositories** (run once)
   ```bash
   for repo in nexus-agent-core nexus-mcp-aws nexus-mcp-custom nexus-mcp-database nexus-mcp-k8s nexus-ui nexus-drone-simulator nexus-kinesis-opensearch; do
     aws ecr create-repository --repository-name $repo --image-scanning-configuration scanOnPush=true --region us-west-2 --profile nexus || true
   done
   ```

3. **Build & push images** (example for Agent Core)
   ```bash
   docker build -t nexus-agent-core:latest services/agent-core
   docker tag nexus-agent-core:latest <account-id>.dkr.ecr.us-west-2.amazonaws.com/nexus-agent-core:latest
   docker push <account-id>.dkr.ecr.us-west-2.amazonaws.com/nexus-agent-core:latest
   ```

   Repeat for:
   - `services/mcp/aws`
   - `services/mcp/custom`
   - `services/mcp/database`
   - `services/mcp/k8s`
   - `services/data-pipeline/kinesis-opensearch`
   - `services/simulators/dji-drone`
   - UI build context (e.g., `kubernetes/ui` or a dedicated front-end directory)

4. **Update manifests**
   - Edit `kubernetes/agent-core/deployment.yaml`, `kubernetes/mcp-services/deployments.yaml`, and `kubernetes/ui/deployment.yaml` with the fully qualified ECR image URIs.

---

## 5. Patch IAM Role ARNs into Service Accounts

Terraform outputs IAM roles but Kubernetes manifests contain placeholders. Update:
- `kubernetes/agent-core/serviceaccount.yaml`
- `kubernetes/mcp-services/serviceaccount.yaml`
- `kubernetes/data-plane/serviceaccounts.yaml`

Example using `yq`:
```bash
yq -i '.metadata.annotations["eks.amazonaws.com/role-arn"] = "arn:aws:iam::<account-id>:role/nexus-dev-agent"' \
  kubernetes/agent-core/serviceaccount.yaml

yq -i 'select(.metadata.name=="aws-mcp").metadata.annotations["eks.amazonaws.com/role-arn"] = "arn:aws:iam::<account-id>:role/nexus-dev-aws-mcp"' \
  kubernetes/mcp-services/serviceaccount.yaml
```
Ensure the annotation values match the actual role names created by Terraform.
Apply the same role ARN updates to `kubernetes/data-plane/serviceaccounts.yaml` so the drone simulator and Kinesis->OpenSearch worker inherit the correct AWS permissions.

---

## 6. Deploy Kubernetes Resources

1. **Validate kubeconfig**
   ```bash
   kubectl config current-context
   ```

2. **Apply the manifests**
   ```bash
   kubectl apply -k kubernetes/
   ```

3. **Verify deployment status**
   ```bash
   kubectl get ns nexus-agent-core nexus-mcp nexus-data
   kubectl get pods -n nexus-agent-core
   kubectl get pods -n nexus-mcp
   kubectl get pods -n nexus-data
   ```

4. **Inspect key workloads**
   - Agent Core logs: `kubectl logs deploy/agent-core -n nexus-agent-core`
   - MCP services: `kubectl get svc -n nexus-mcp`
   - OpenSearch service: `kubectl get svc -n nexus-observability`
   - UI service: `kubectl get svc nexus-ui -n nexus-agent-core`

5. **(Optional) Local workflow test**
   ```bash
   kubectl port-forward -n nexus-agent-core svc/agent-core 8080:80
   curl -X POST http://localhost:8080/workflow/execute \
     -H 'Content-Type: application/json' \
     -d '{"method":"workflow/execute","params":{"task":"weather"}}'
   ```

---

## 7. Integrate UI with API Gateway

1. Retrieve the API invoke URL (`terraform output ui_api_gateway_url`).
2. Update `kubernetes/ui/configmap.yaml` -> `API_GATEWAY_URL`.
3. Apply the ConfigMap and restart the deployment:
   ```bash
   kubectl apply -f kubernetes/ui/configmap.yaml
   kubectl rollout restart deploy/nexus-ui -n nexus-agent-core
   ```
4. (Optional) If using a custom domain, ensure the ACM certificate ARN is set in `terraform/api.tf` and DNS records point to API Gateway.

---

## 8. Post-Deployment Validation

1. **Agent Core & MCP health** – Pods in `Running` state; `/health` endpoints reachable.
2. **Token issuance** –
   ```bash
   curl -X POST $(terraform output -raw ui_api_gateway_url)/auth \
     -H 'Content-Type: application/json' \
     -d '{"user":"alice","ttl":1800}' | jq
   ```
   Ensure the response includes `tokenType`, `credentials.accessKeyId`, and stream names (`kinesisData`, `kinesisVideo`, `firehoseDelivery`).
3. **Client stream access** – Using the returned credentials, publish a test record to `${project}-${env}-client-intake` and confirm Firehose `${project}-${env}-client-to-lake` delivers to the bronze bucket `client/` prefix.
4. **Primary Firehose delivery** – Confirm the main delivery stream shows successful writes in CloudWatch metrics.
5. **Lake Formation** – Validate data location registration and administrator access via the AWS console.
6. **UI access** – Access the UI (via port-forward, LoadBalancer, or Ingress) and verify authenticated workflows.

7. **OpenSearch indexing** – Hit `http://<opensearch-lb>:9200/drone-events/_search` (or port-forward the service) and confirm documents with `normalized.latitude/longitude` values are present.
8. **Autoscaling** – Inspect the KEDA scaled object (`kubectl describe scaledobject kinesis-opensearch-scaler -n nexus-data`) and verify replica counts change under simulated load.

---

## 9. Operational Hardening (Recommended)
- Replace the sample Lambda token service with Amazon Cognito, IAM Identity Center, or OIDC for managed identity, signing, and revocation.
- Store sensitive config (API tokens, map keys) in AWS Secrets Manager or Parameter Store and mount via something like External Secrets Operator.
- Harden OpenSearch (TLS, fine-grained RBAC, snapshots) before exposing dashboards outside the cluster.
- Enable AWS CloudTrail, Config, and GuardDuty for compliance monitoring; consider AWS Security Hub for centralized findings.
- Instrument services with Prometheus metrics and export to Amazon Managed Prometheus or CloudWatch metrics. Monitor both primary and client Kinesis/Firehose channels.
- Configure CI/CD pipelines to automate Terraform plans/applies, container builds, and Kubernetes deployments (e.g., GitHub Actions, CodePipeline, Argo CD).
- Implement automated tests that exercise token issuance and streaming ingestion (e.g., `kinesis put-record` smoke tests).

---

## 10. Cleanup

1. **Remove Kubernetes workloads**
   ```bash
   kubectl delete -k kubernetes/
   ```

2. **Destroy Terraform resources**
   ```bash
   cd terraform
   terraform destroy
   ```

3. **Delete ECR repositories** *(optional)*
   ```bash
   for repo in nexus-agent-core nexus-mcp-aws nexus-mcp-custom nexus-mcp-database nexus-mcp-k8s nexus-ui nexus-drone-simulator nexus-kinesis-opensearch; do
     aws ecr delete-repository --repository-name $repo --force --region us-west-2 --profile nexus || true
   done
   ```

4. **Revoke outstanding tokens** *(optional)* – If you replaced the sample token service, revoke/expire credentials using your identity provider.

---

Deployment is complete once infrastructure, Kubernetes workloads, token issuance, and data delivery paths are validated. Maintain this guide alongside versioned releases to reflect evolving workflows.
