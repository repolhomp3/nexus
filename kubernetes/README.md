# Kubernetes Manifests

Base manifests for Nexus workloads intended to run on the provisioned EKS cluster.

## Structure

- `namespaces.yaml` – Creates `nexus-agent-core`, `nexus-mcp`, and `nexus-data` namespaces.
- `agent-core/` – Python orchestrator service account, config (including primary + client pipeline identifiers), deployment, and service.
- `mcp-services/` – AWS, custom, database, and Kubernetes MCP Deployments plus dedicated service accounts.
- `ui/` – Front-end deployment exposing configuration and telemetry map.

Combine resources with Kustomize:

```bash
kubectl apply -k .
```

## Post-Apply Tasks

- Patch service-account annotations with the IAM role ARNs returned by Terraform.
- Update container image references to match built images in your registries.
- Replace placeholder API Gateway URL, Mapbox token secret names, and (if renamed) the stream identifiers inside `agent-core/configmap.yaml`.
- Add Ingress or service mesh manifests as needed for external access.
