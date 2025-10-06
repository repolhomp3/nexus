locals {
  common_tags = merge({
    Project     = var.project
    Environment = var.environment
  }, var.tags)

  name_prefix = "${var.project}-${var.environment}" 

  kubernetes_namespaces = {
    agent_core   = "nexus-agent-core"
    mcp_services = "nexus-mcp"
    data_plane   = "nexus-data"
  }

  medallion_layers = ["bronze", "silver", "gold", "vibranium"]
}
