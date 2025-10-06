data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  selected_azs = length(var.availability_zones) > 0 ? var.availability_zones : slice(data.aws_availability_zones.available.names, 0, 3)
}

module "network" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.1"

  name = "${local.name_prefix}-vpc"
  cidr = var.vpc_cidr

  azs             = local.selected_azs
  private_subnets = [for index, az in local.selected_azs : cidrsubnet(var.vpc_cidr, 4, index)]
  public_subnets  = [for index, az in local.selected_azs : cidrsubnet(var.vpc_cidr, 4, index + 8)]

  enable_nat_gateway     = true
  enable_dns_hostnames   = true
  enable_dns_support     = true
  private_subnet_tags    = { "kubernetes.io/role/internal-elb" = "1" }
  public_subnet_tags     = { "kubernetes.io/role/elb" = "1" }
  map_public_ip_on_launch = true

  tags = local.common_tags
}
