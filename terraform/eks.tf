module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.4"

  cluster_name    = "${local.name_prefix}-eks"
  cluster_version = var.eks_version

  cluster_endpoint_public_access = true

  vpc_id                   = module.network.vpc_id
  subnet_ids               = module.network.private_subnets
  control_plane_subnet_ids = module.network.private_subnets

  enable_irsa = true

  cluster_addons = {
    coredns = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
  }

  eks_managed_node_group_defaults = {
    ami_type     = "AL2_x86_64"
    instance_types = ["m6i.large"]
    disk_size    = 80
  }

  eks_managed_node_groups = {
    default = {
      desired_size = 3
      min_size     = 2
      max_size     = 6
      subnet_ids   = module.network.private_subnets
      instance_types = ["m6i.large"]
      capacity_type = "ON_DEMAND"
      labels = {
        role = "general"
      }
    }
    mcp = {
      desired_size = 2
      min_size     = 1
      max_size     = 4
      subnet_ids   = module.network.private_subnets
      instance_types = ["m6i.large"]
      capacity_type = "ON_DEMAND"
      labels = {
        role = "mcp"
      }
      taints = {
        "dedicated" = {
          value  = "mcp"
          effect = "NO_SCHEDULE"
        }
      }
    }
  }

  tags = local.common_tags
}

data "aws_eks_cluster" "cluster" {
  name = module.eks.cluster_name
}

data "aws_eks_cluster_auth" "cluster" {
  name = module.eks.cluster_name
}

# Optional Karpenter provisioning for workload-aware autoscaling.
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 20.4"

  count = var.enable_karpenter ? 1 : 0

  cluster_name                = module.eks.cluster_name
  cluster_endpoint            = module.eks.cluster_endpoint
  cluster_certificate_authority_data = module.eks.cluster_certificate_authority_data

  irsa_oidc_provider_arn = module.eks.oidc_provider_arn
  namespace              = local.kubernetes_namespaces["mcp_services"]

  tags = local.common_tags
}
