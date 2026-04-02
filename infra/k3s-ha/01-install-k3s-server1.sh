#!/bin/bash
# =============================================================================
# 01-install-k3s-server1.sh — Instala el primer nodo K3s (cluster-init)
#
# Ejecutado SOLO en k3s-control-1 (192.168.0.185).
# Inicializa el clúster embedded etcd K3s HA.
#
# Variables:
#   K3S_TOKEN     — token compartido entre los 3 nodos
#   KUBE_VIP_IP   — 192.168.0.150
#   NODE_IP       — 192.168.0.185
#   K3S_INTERFACE — ens3
# =============================================================================
set -euo pipefail

echo ""
echo "  ┌─────────────────────────────────────────────────────────"
echo "  │  01-install-k3s-server1 — Inicializando clúster HA"
echo "  │  Node IP: ${NODE_IP}   VIP: ${KUBE_VIP_IP}"
echo "  └─────────────────────────────────────────────────────────"

# ── Idempotencia: saltar si K3s ya está running ───────────────────────────────
if systemctl is-active --quiet k3s 2>/dev/null; then
  echo "  ✓ K3s ya está running en ${NODE_IP} — saltando instalación"
  echo "    (para reinstalar: systemctl stop k3s && k3s-uninstall.sh)"
  kubectl get nodes 2>/dev/null || true
  exit 0
fi

# ── Instalar K3s (primer nodo, --cluster-init) ────────────────────────────────
echo "→ Instalando K3s con --cluster-init..."

curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --cluster-init \
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
  --write-kubeconfig-mode=644 \
  --etcd-expose-metrics=true" sh -

# ── Esperar que el API server responda ────────────────────────────────────────
echo "→ Esperando que el API server arranque..."
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
for i in $(seq 1 30); do
  if kubectl get nodes &>/dev/null 2>&1; then
    echo "  ✓ API server responde"
    break
  fi
  echo "  ... intento ${i}/30"
  sleep 5
done

# El nodo estará NotReady hasta que Cilium CNI esté instalado — es normal
echo "→ Estado del nodo (NotReady esperado hasta instalar Cilium):"
kubectl get nodes -o wide || true

# ── Guardar kubeconfig para uso local ─────────────────────────────────────────
echo "→ Kubeconfig disponible en /etc/rancher/k3s/k3s.yaml"
echo "  Para copiar a tu máquina local:"
echo "  scp ubuntu@${NODE_IP}:/etc/rancher/k3s/k3s.yaml ~/.kube/k3s-ha.yaml"
echo "  Luego reemplazar 127.0.0.1 por ${KUBE_VIP_IP}:"
echo "  sed -i 's/127.0.0.1/${KUBE_VIP_IP}/g' ~/.kube/k3s-ha.yaml"

echo ""
echo "  ✅ K3s server-1 instalado. Próximo paso: 02-install-kube-vip.sh"
