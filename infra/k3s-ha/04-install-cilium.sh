#!/bin/bash
# =============================================================================
# 04-install-cilium.sh — Instala Cilium CNI en el clúster K3s HA
#
# Ejecutado desde k3s-control-1 DESPUÉS de que kube-vip esté activo.
# Cilium reemplaza completamente kube-proxy usando eBPF.
#
# Requisitos: Helm instalado (se instala automáticamente si no existe)
# =============================================================================
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
CILIUM_VERSION="1.19.2"   # Última estable — compatible con K8s 1.34 (K3s v1.34.x)

# IMPORTANTE: Usar la IP real del nodo (NO el VIP) durante el bootstrap.
# El VIP necesita Cilium para funcionar → chicken-and-egg si usamos el VIP aquí.
# Después de que Cilium esté running, el VIP 192.168.0.150 funciona normalmente.
API_HOST="${NODE_IP:-192.168.0.185}"

echo ""
echo "  ┌─────────────────────────────────────────────────────────
  │  04-install-cilium v${CILIUM_VERSION}
  │  kube-proxy replacement vía eBPF
  │  API server bootstrap: ${API_HOST}:6443 (IP real del nodo)
  │  VIP final: ${KUBE_VIP_IP} (activo después de que Cilium arranque)
  └─────────────────────────────────────────────────────────
"

# ── Instalar Helm si no está ──────────────────────────────────────────────────
if ! command -v helm &>/dev/null; then
  echo "→ Instalando Helm..."
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash -s -- --no-sudo 2>/dev/null || \
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# ── Repo Cilium ───────────────────────────────────────────────────────────────
helm repo add cilium https://helm.cilium.io/ 2>/dev/null || true
helm repo update cilium

# ── Instalar Cilium ───────────────────────────────────────────────────────────
echo "→ Instalando Cilium ${CILIUM_VERSION}..."

helm upgrade --install cilium cilium/cilium \
  --version "${CILIUM_VERSION}" \
  --namespace kube-system \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost="${API_HOST}" \
  --set k8sServicePort=6443 \
  --set ipam.mode=kubernetes \
  --set operator.replicas=1 \
  --set operator.rollOutPods=true \
  --set rollOutCiliumPods=true \
  --set hubble.relay.enabled=false \
  --set hubble.ui.enabled=false \
  --set routingMode=tunnel \
  --set tunnelProtocol=vxlan \
  --set bpf.masquerade=true \
  --set prometheus.enabled=false \
  --set operator.prometheus.enabled=false \
  --timeout=600s \
  --wait

echo ""
echo "→ Verificando instalación de Cilium..."
kubectl -n kube-system get pods -l k8s-app=cilium -o wide

# ── Esperar que los nodos pasen a Ready ───────────────────────────────────────
echo ""
echo "→ Esperando que los nodos estén Ready..."
for i in $(seq 1 24); do
  READY=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready " || echo "0")
  TOTAL=$(kubectl get nodes --no-headers 2>/dev/null | wc -l || echo "0")
  echo "  Nodos Ready: ${READY}/${TOTAL} (intento ${i}/24)"
  if [ "${READY}" -ge 1 ]; then
    echo "  ✓ Al menos 1 nodo Ready — cluster operativo"
    break
  fi
  sleep 10
done

echo ""
kubectl get nodes -o wide

echo ""
echo "  ✅ Cilium instalado"
echo ""
echo "  Próximo paso: unir k3s-control-2 y k3s-control-3 con 03-join-k3s-servers.sh"
echo "  Luego instalar Traefik con 05-install-traefik.sh"
