# Project Nexus Architecture

This document describes the Project Nexus architecture, component responsibilities, and data flows. It is written so that a technical writer or solutions architect can convert the narrative into high-fidelity architecture diagrams without referring to additional sources.

---

## 1. Architectural Overview

**Mission**: Nexus ingests streaming and batch data, applies AI-powered enrichment, and disseminates curated intelligence to downstream consumers. The platform couples AWS-managed services for durability with Kubernetes-hosted MCP (Model Context Protocol) services and a Bedrock-enabled agent core.

**Deployment Region**: AWS `us-west-2` (configurable). All resources share a common naming prefix `${project}-${environment}` (defaults: `nexus-dev`).

**High-Level Layers**:
1. **Edge & Experience Layer** – Amazon API Gateway, Lambda authentication/token service, and the Nexus UI (running on EKS) expose secure endpoints for operators and data producers.
2. **Control & Orchestration Layer** – Amazon EKS hosts the Agent Core and MCP services, which coordinate workloads and invoke Bedrock models.
3. **Data & Intelligence Layer** – Amazon Kinesis (Data Streams & Video Streams) captures inbound telemetry; Kinesis Firehose and the medallion S3 data lake store, refine, and govern data. Lake Formation manages metadata and access.

---

## 2. Component Inventory

### 2.1 AWS Networking & Compute
- **VPC** (`/16`) with three Availability Zones.
  - Public subnets: load balancers, NAT gateways.
  - Private subnets: EKS worker nodes, data services.
- **NAT Gateway** in each AZ for outbound internet access from private subnets.
- **Amazon EKS Cluster** (`${project}-${environment}-eks`)
  - Managed node group `general` (on-demand, label `role=general`).
  - Managed node group `mcp` (tainted `dedicated=mcp:NoSchedule`) for MCP pods.
  - Optional Karpenter provisioner (namespace `nexus-mcp`) for workload-aware autoscaling.

### 2.2 Identity & Access
- **IAM Roles for Service Accounts (IRSA)**
  - `nexus-agent-core/agent-orchestrator` → `aws_iam_role.agent_irsa`
    - Permissions: Bedrock invoke/list, Kinesis (primary + client streams), Firehose (primary + client), S3 medallion buckets (Get/List/Put).
  - `nexus-mcp/aws-mcp` → `aws_iam_role.aws_mcp_irsa`
    - Permissions: Bedrock invoke/list, Glue job operations, S3 list, Lake buckets.
- **Lambda Execution Role** for authentication/token function (CloudWatch logs, Secrets Manager reads, STS assume role).
- **Bearer Token Role** (`aws_iam_role.kinesis_bearer`)
  - Trusts the Lambda execution role; scoped to client-facing Kinesis Data Stream, Kinesis Video Stream, and Firehose delivery stream. STS credentials issued from this role are embedded in bearer tokens.
- **Firehose Role** to consume Kinesis Data Streams (primary + client) and deliver to S3.
- **Lake Formation Admin** – defaults to current AWS identity; configurable via Terraform variable `lakeformation_admins`.

### 2.3 Streaming & Storage
- **Amazon Kinesis Data Streams**
  - Primary ingest `${prefix}-intake`: 2 shards, 48-hour retention, used by internal Nexus workflows.
  - Client ingest `${prefix}-client-intake`: 1 shard, 24-hour retention, exposed via bearer tokens to authenticated producers/consumers.
- **Amazon Kinesis Video Streams**
  - `${prefix}-telemetry`: 24-hour retention for internal telemetry.
  - `${prefix}-client-telemetry`: 12-hour retention for client-produced video/sensor data.
- **Amazon Kinesis Firehose Delivery Streams**
  - `${prefix}-to-lake`: Sources the primary Data Stream, delivers GZIP-compressed objects to S3 bronze.
  - `${prefix}-client-to-lake`: Sources the client Data Stream, writes to S3 bronze under `client/` prefix.
- **Amazon S3 (Medallion Architecture)**
  - Bronze (`${prefix}-bronze-${region}`) – raw immutable data (including Firehose client prefix).
  - Silver (`${prefix}-silver-${region}`) – cleansed & structured outputs.
  - Gold (`${prefix}-gold-${region}`) – analytics-ready aggregates.
  - Vibranium (`${prefix}-vibranium-${region}`) – high-trust curated intelligence.
  - All buckets: versioning enabled, AES-256 encryption, tagged with `MedallionTier`.
- **AWS Lake Formation**
  - Registers each bucket as a data location.
  - Grants DATA_LOCATION_ACCESS to administrators (default caller or configured list).

### 2.4 Control Plane Services (EKS)
- **Namespace `nexus-agent-core`**
  - Deployment `agent-core`: Python service exposing HTTP API `POST /workflow/execute`, `GET /health`, `GET /metrics`. ConfigMap includes Bedrock models and both primary/client pipeline identifiers.
  - Service `agent-core`: ClusterIP on port 80 -> container port 8000.
  - Deployment `nexus-ui`: Operator UI configured with API Gateway invoke URL and map style.
  - ConfigMaps: `agent-core-config` (settings.yaml), `nexus-ui-config` (UI settings).
- **Namespace `nexus-mcp`**
  - Deployment `aws-mcp`: exposes S3, Glue, Bedrock tooling. ServiceAccount annotated with IRSA role.
  - Deployment `custom-mcp`: sample key-value + weather enrichment service.
  - Deployment `database-mcp`: SQLite-backed SQL executor (emptyDir for ephemeral storage).
  - Deployment `k8s-mcp`: Kubernetes automation (list pods, scale deployments, troubleshoot pods).
  - Services: ClusterIPs for each MCP deployment, port 80 -> container 8000.
  - ServiceAccounts: discrete accounts per MCP service, enabling least-privilege policies.
- **Namespace `nexus-data`**
  - Reserved for future data-processing workloads (Glue jobs, Spark, etc.).

### 2.5 Edge & Experience
- **Amazon API Gateway v2 (HTTP API)** `${prefix}-ui`
  - Route `POST /auth` proxied to Lambda.
  - Stage `prod` with CloudWatch access logs.
  - Optional custom domain via ACM certificate.
- **AWS Lambda Function** `${prefix}-auth`
  - Accepts authentication requests, clamps TTL (15–60 minutes), assumes the bearer role via STS, and returns bearer token metadata plus temporary AWS credentials alongside stream identifiers.
- **Front-End UI**
  - Running in EKS; uses API Gateway for auth flows and MCP/Agent endpoints for configuration & telemetry.

### 2.6 Observability
- **CloudWatch Log Groups**
  - `/aws/kinesisfirehose/${prefix}-firehose`
  - `/aws/kinesisfirehose/${prefix}-client-firehose`
  - `/aws/lambda/${prefix}-auth`
  - `/aws/apigateway/${prefix}-ui`
- **Agent Core Metrics**
  - Exposes placeholder Prometheus-style metrics on `/metrics` (expand as needed).

---

## 3. Data Flow Narratives

### 3.1 Client Authentication to Bronze Path
1. A producer invokes `POST /auth` on API Gateway with user metadata and desired TTL.
2. Lambda validates configuration, assumes the bearer IAM role via STS, and returns a bearer token payload containing temporary AWS credentials, TTL, and the names of the client data/video streams and Firehose delivery stream.
3. The producer uses the STS credentials (SigV4) to push records to **Kinesis Data Stream `${prefix}-client-intake`** or video media to **Kinesis Video Stream `${prefix}-client-telemetry`**.
4. **Kinesis Firehose `${prefix}-client-to-lake`** reads from the client Data Stream, buffers, compresses, and writes payloads into the **Bronze S3 bucket** (`client/` prefix). CloudWatch logs capture delivery successes/failures.

### 3.2 Internal Ingestion to Bronze
1. Internal sources push events to **Kinesis Data Stream `${prefix}-intake`**; video/sensor payloads to **Kinesis Video Stream `${prefix}-telemetry`**.
2. **Kinesis Firehose `${prefix}-to-lake`** consumes the primary stream and lands output in the bronze bucket root.

### 3.3 Orchestration & Processing
1. **Agent Core** consumes stream events (primary channel), reads configuration from the ConfigMap, and orchestrates workflows.
2. Depending on the workflow:
   - Calls **AWS MCP** for infrastructure-aware actions (S3 bucket inventory, Glue jobs, Bedrock inference with service-specific credentials).
   - Invokes **Custom MCP** for domain-specific enrichment (weather lookup, key-value caching).
   - Executes **Database MCP** for ad-hoc SQL queries against the embedded SQLite store (placeholder for future RDS/Aurora integration).
   - Utilizes **K8s MCP** to introspect or remediate Kubernetes resources.
3. Agent Core may also invoke **Amazon Bedrock** directly using its IRSA role and configured model IDs (e.g., `anthropic.claude-3-sonnet-20240229-v1:0`, `amazon.titan-text-express-v1`).
4. MCP responses and Bedrock outputs feed back into the agent workflow. Results are serialized as JSON payloads and may be written back to the data lake via MCP services.

### 3.4 Lake Formation & Medallion Advancement
1. Processed outputs are written by MCP services or downstream pipelines into the **Silver** bucket (cleansed datasets) and **Gold** bucket (aggregated intelligence).
2. High-confidence, curated insights land in the **Vibranium** bucket, ready for dissemination to mission partners.
3. Lake Formation policies ensure only authorized principals can read/write specific tiers. Administrators add data catalogs, databases, or tables referencing these buckets for analytics services (Athena, Glue Data Catalog, Redshift Spectrum).

### 3.5 Dissemination & UI Experience
1. **Nexus UI** retrieves authentication tokens via API Gateway + Lambda.
2. Authenticated sessions allow operators to request data views, configure source/destination mappings, and launch workflows.
3. MCP dissemination services push results to external systems (extendable pattern).
4. Telemetry overlays (map visualization) pull data from Firehose-fed buckets or live streams, using tokens stored in ConfigMaps/Secrets.

---

## 4. Interaction Patterns for Diagramming

When drafting architecture diagrams, depict the following interaction sets:

1. **Edge Authentication Flow**
   - User → API Gateway → Lambda Auth (STS AssumeRole) → returns bearer payload → User uses STS credentials to call Kinesis Data/Video Streams and Firehose.

2. **Client Streaming Pipeline**
   - Producers → Kinesis Data Stream `${prefix}-client-intake` → Firehose `${prefix}-client-to-lake` → S3 Bronze (`client/` prefix) → Lake Formation.
   - Producers (video) → Kinesis Video Stream `${prefix}-client-telemetry` → downstream analytics.

3. **Internal Streaming Pipeline**
   - Internal producers → Kinesis Data Stream `${prefix}-intake` → Firehose `${prefix}-to-lake` → S3 Bronze → Lake Formation.

4. **Control Plane Workflow**
   - Agent Core (EKS) ↔ MCP Services (AWS/Custom/Database/K8s) via ClusterIP services.
   - Agent Core → Bedrock (via IRSA) for inference.

5. **Data Promotion**
   - Bronze → Silver → Gold → Vibranium S3 buckets (medallion flow) with Lake Formation policy enforcement.

6. **Observability & IAM**
   - CloudWatch log groups for API, Lambda, Firehose (primary + client).
   - IAM relationships: Lambda execution role assumes bearer role; IRSA bindings map Kubernetes service accounts to IAM roles.

---

## 5. Scaling & Availability Considerations
- **Kinesis Shards** – Scale both primary and client streams based on ingest throughput; adjust Firehose buffering parameters to meet latency SLAs.
- **EKS Node Groups** – General workloads run on default group; MCP-specific workloads can be isolated via taints/tolerations. Karpenter (optional) elastically provisions nodes.
- **Bedrock** – Managed service; monitor invocation quotas and apply model-specific guardrails.
- **Data Lake** – Leverage S3 lifecycle policies for cost management; optional replication for DR scenarios.
- **API Layer** – API Gateway is multi-AZ; Lambda scales automatically. UI replicas set via Kubernetes Deployment.

---

## 6. Security Controls
- **Network Segmentation** – Public subnets host ingress/egress; all workloads run inside private subnets.
- **IAM Boundaries** – IRSA restricts pods to scoped AWS permissions. The bearer role isolates client access to client-specific Kinesis resources, limiting blast radius of issued credentials.
- **Encryption** – S3 (SSE-S3), Kinesis (in-transit TLS, optional KMS), API Gateway (TLS 1.2). Consider enabling KMS CMKs for Kinesis streams and Firehose if required.
- **Token Handling** – Lambda clamps TTL to 15–60 minutes. Replace the simple bearer payload with signed JWTs or Cognito-issued tokens for production deployments.
- **Auditing** – CloudTrail captures IAM/STSI events; CloudWatch logs maintain execution traces for Lambda, Firehose, and API Gateway.

---

## 7. Extensibility Hooks
- **Additional MCP Services** – Follow the `services/mcp/*` pattern: new Deployment, ServiceAccount, IRSA policy, ConfigMap updates, and service registration in Agent Core.
- **Workflow Automation** – Integrate AWS Step Functions or EventBridge to trigger Agent Core workflows automatically.
- **External Integrations** – Build dissemination connectors (e.g., SNS topics, third-party APIs) as MCP services or Lambda functions invoked by the agent.
- **Analytics Tooling** – Register Lake Formation data locations with AWS Glue Data Catalog, Amazon Athena, or Amazon QuickSight for BI/analytics.
- **Token Exchange** – Swap the Lambda token service for Cognito, API Gateway Lambda authorizers, or IAM Identity Center to fit enterprise identity requirements.

---

## 8. Reference Implementation Notes
- ConfigMaps store queue/bucket names, ensuring workloads remain environment-agnostic.
- Placeholder account IDs (`123456789012`) must be replaced with real AWS accounts prior to deployment.
- The sample UI and Lambda are scaffolds; production rollouts should integrate enterprise SSO, hardened token issuance, and audited dissemination endpoints.

---

Use this document as the authoritative source when producing architecture visuals, system runbooks, or onboarding material for engineering and operations teams.
