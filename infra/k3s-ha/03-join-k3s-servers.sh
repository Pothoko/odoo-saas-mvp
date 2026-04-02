#!/bin/bash
# =============================================================================
# 03-join-k3s-servers.sh — Une un nodo al clúster K3s HA existente
#
# Ejecutado en k3s-control-2 y k3s-control-3 DESPUÉS de que Cilium esté
# corriendo en el nodo 1 y el VIP 192.168.0.150 esté activo.
#
# Variables:
#   K3S_TOKEN     — mismo token que usó server-1
#   KUBE_VIP_IP   — 192.168.0.150 (VIP del API server)
#   NODE_IP       — IP interna de este nodo (192.168.0.211 o .243)
#   NODE_NAME     — k3s-2 o k3s-3
# =============================================================================
set -euo pipefail

echo ""
echo "  ┌─────────────────────────────────────────────────────────"
echo "  │  03-join-k3s-servers — ${NODE_NAME} (${NODE_IP})"
echo "  │  Uniéndose al clúster en VIP ${KUBE_VIP_IP}"
echo "  └─────────────────────────────────────────────────────────"

# ── Idempotencia: saltar si ya está unido al clúster ─────────────────────────
if systemctl is-active --quiet k3s 2>/dev/null; then
  echo "  ✓ ${NODE_NAME} ya está en el clúster — saltando join"
  echo "    Estado: $(systemctl is-active k3s)"
  exit 0
fi

# ── Verificar que el VIP responde antes de intentar unirse ───────────────────
echo "→ Verificando VIP ${KUBE_VIP_IP}:6443..."
for i in $(seq 1 12); do
  if nc -z -w3 "${KUBE_VIP_IP}" 6443 2>/dev/null; then
    echo "  ✓ API server en ${KUBE_VIP_IP}:6443 responde"
    break
  fi
  echo "  ... esperando VIP (intento ${i}/12)..."
  sleep 10
done

# ── Instalar K3s como nodo adicional del clúster ──────────────────────────────
echo "→ Instalando K3s y uniéndose al clúster..."

curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --server=https://${KUBE_VIP_IP}:6443 \
  --token=${K3S_TOKEN} \
  --node-ip=${NODE_IP} \
  --advertise-address=${NODE_IP} \
  --tls-san=${KUBE_VIP_IP} \
  --tls-san=${NODE_IP} \
  --disable=traefik \
  --disable=servicelb \
  --disable=local-storage \
  --flannel-backend=none \
  --disable-network-policy \
  --disable-kube-proxy \
  --write-kubeconfig-mode=644" sh -

# ── Verificar que el nodo se unió ─────────────────────────────────────────────
echo "→ Verificando estado del nodo..."
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
sleep 15
kubectl get nodes -o wide || true

echo ""
echo "  ✅ ${NODE_NAME} unido al clúster"
echo "  El nodo estará NotReady hasta que Cilium propague el CNI"
