resource "helm_release" "keda" {
  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  version    = "2.14.2"
  namespace  = "keda"

  create_namespace = true

  values = [jsonencode({
    podSecurityContext = {
      runAsNonRoot = true
      runAsUser    = 1001
    }
  })]

  depends_on = [module.eks]
}
