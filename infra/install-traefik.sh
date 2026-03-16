#!/usr/bin/env bash
# infra/install-traefik.sh
# Install Helm (if missing) then install/upgrade Traefik on an existing K3s cluster.
# Run as root: bash odoo-saas-mvp/infra/install-traefik.sh
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# ── Helm ──────────────────────────────────────────────────────────────────────
if ! command -v helm &>/dev/null; then
  echo "==> Installing Helm …"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
echo "    Helm: $(helm version --short)"

# ── Traefik ───────────────────────────────────────────────────────────────────
echo "==> Installing/upgrading Traefik via Helm …"
helm repo add traefik https://helm.traefik.io/traefik 2>/dev/null || true
helm repo update

helm upgrade --install traefik traefik/traefik \
  --namespace kube-system \
  --set ports.web.exposedPort=80 \
  --set ports.websecure.exposedPort=443 \
  --set providers.kubernetesCRD.enabled=true \
  --set providers.kubernetesIngress.enabled=true \
  --wait --timeout 120s

echo "==> Traefik ready."
kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik
