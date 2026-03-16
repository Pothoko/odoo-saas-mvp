#!/usr/bin/env bash
# infra/install-k3s.sh
# Install K3s (WITHOUT built-in Traefik — we install Traefik via install-traefik.sh).
# Run as root on the VM:  bash odoo-saas-mvp/infra/install-k3s.sh
set -euo pipefail

echo "==> Installing K3s …"
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode 644 \
  --disable traefik

echo "==> Waiting for K3s node to be Ready …"
until kubectl get nodes 2>/dev/null | grep -q " Ready"; do
  sleep 5
done
echo "    Node ready."

echo "==> K3s installation complete."
echo "    Run next:  bash infra/install-traefik.sh"
echo "    Then:      bash infra/apply-manifests.sh"
