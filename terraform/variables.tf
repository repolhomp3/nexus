variable "project" {
  description = "Project namespace used for tagging and resource names."
  type        = string
  default     = "nexus"
}

variable "environment" {
  description = "Deployment environment identifier."
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-west-2"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones to use. Leave empty to auto-discover."
  type        = list(string)
  default     = []
}

variable "eks_version" {
  description = "Kubernetes version for the EKS control plane."
  type        = string
  default     = "1.29"
}

variable "enable_karpenter" {
  description = "Toggle to deploy Karpenter node provisioning."
  type        = bool
  default     = true
}

variable "lakeformation_admins" {
  description = "Lake Formation administrator IAM principal ARNs."
  type        = list(string)
  default     = []
}

variable "agent_bedrock_models" {
  description = "List of Bedrock model IDs that the agent is allowed to invoke."
  type        = list(string)
  default     = [
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "amazon.titan-text-express-v1"
  ]
}

variable "ui_domain_name" {
  description = "Optional custom domain for the Nexus UI API Gateway."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Additional tags to apply to supported resources."
  type        = map(string)
  default     = {}
}
