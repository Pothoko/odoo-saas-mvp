#!/usr/bin/env bash
# infra/install-k3s.sh
# Install K3s on an Ubuntu Hetzner VM for the Odoo SaaS MVP.
# Run as root on the VM.
set -euo pipefail

echo "==> Installing K3s …"
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode 644 \
  --disable traefik \   # we use Traefik via Helm for CRDs
  --cluster-init

# Wait for K3s to be ready
echo "==> Waiting for K3s node to be Ready …"
until kubectl get nodes | grep -q " Ready"; do sleep 5; done

echo "==> Installing Traefik (with CRDs) via Helm …"
helm repo add traefik https://helm.traefik.io/traefik
helm repo update
helm upgrade --install traefik traefik/traefik \
  --namespace kube-system \
  --set ports.web.exposedPort=80 \
  --set ports.websecure.exposedPort=443 \
  --set providers.kubernetesCRD.enabled=true \
  --set providers.kubernetesIngress.enabled=true \
  --wait

echo "==> K3s + Traefik installation complete."
echo "    Kubeconfig: /etc/rancher/k3s/k3s.yaml"
