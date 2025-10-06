# Nexus Service Implementations

Python sources for workloads deployed via the Kubernetes manifests.

## Layout

- `agent-core/` – Main orchestration service calling Bedrock and MCP endpoints.
- `mcp/aws/` – AWS integration MCP wrapping S3, Bedrock, and Glue tools.
- `mcp/custom/` – Example MCP providing key-value storage and weather enrichment.
- `mcp/database/` – SQLite-backed MCP for executing SQL queries.
- `mcp/k8s/` – Kubernetes MCP for cluster introspection and actions.

Each folder includes a minimal `requirements.txt` to seed container images. Build and publish container artifacts that execute the corresponding `*-server.py` or `agent-core.py` entrypoints.
