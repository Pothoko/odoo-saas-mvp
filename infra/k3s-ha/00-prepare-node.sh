#!/bin/bash
# =============================================================================
# 00-prepare-node.sh — Prepara cada nodo K3s (Ubuntu 24.04)
#
# Ejecutado por deploy-k3s-cluster.sh en los 3 nodos via SSH.
# Instala: ceph-common, módulo rbd, ajustes kernel para K3s+Cilium.
#
# Variables recibidas via env:
#   NODE_NAME  — nombre del nodo (k3s-1, k3s-2, k3s-3)
#   NODE_IP    — IP interna (192.168.0.x)
# =============================================================================
set -euo pipefail

echo ""
echo "  ┌─────────────────────────────────────────────────────────"
echo "  │  00-prepare-node — ${NODE_NAME} (${NODE_IP})"
echo "  └─────────────────────────────────────────────────────────"

# ── Sistema base ──────────────────────────────────────────────────────────────
echo "→ Actualizando paquetes..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  curl wget gnupg2 ca-certificates \
  net-tools iproute2 iputils-ping \
  jq htop nfs-common open-iscsi \
  netcat-openbsd

# ── Ceph client — REQUERIDO para que el CSI driver monte RBD ─────────────────
echo "→ Instalando ceph-common..."
apt-get install -y -qq ceph-common

# Verificar version instalada
ceph --version 2>/dev/null || { echo "  ✗ ceph-common no instalado correctamente"; exit 1; }
echo "  ✓ ceph-common instalado"

# ── Módulo kernel RBD — REQUERIDO para montar volúmenes Ceph RBD ─────────────
echo "→ Cargando módulo rbd..."
modprobe rbd
echo "rbd" | tee /etc/modules-load.d/rbd.conf > /dev/null
lsmod | grep -q rbd && echo "  ✓ módulo rbd cargado" || { echo "  ✗ Error cargando rbd"; exit 1; }

# ── Ajustes kernel para K3s + Cilium (eBPF) ──────────────────────────────────
echo "→ Configurando parámetros kernel..."
cat > /etc/sysctl.d/99-k3s-cilium.conf << 'EOF'
# K3s
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
# Cilium / eBPF
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
# kube-vip ARP
net.ipv4.conf.all.arp_announce = 2
net.ipv4.conf.all.arp_ignore = 1
EOF
sysctl --system -q
echo "  ✓ parámetros kernel aplicados"

# ── Deshabilitar swap (requerido por K3s) ─────────────────────────────────────
echo "→ Deshabilitando swap..."
swapoff -a
sed -i '/\bswap\b/d' /etc/fstab
echo "  ✓ swap deshabilitado"

# ── Verificar conectividad con Ceph MONs ──────────────────────────────────────
echo "→ Verificando conectividad con Ceph MONs..."
CEPH_MONS=("10.40.1.240" "10.40.1.241")
for mon in "${CEPH_MONS[@]}"; do
  if nc -z -w3 "${mon}" 6789 2>/dev/null; then
    echo "  ✓ ${mon}:6789 alcanzable"
  else
    echo "  ✗ ${mon}:6789 NO alcanzable"
    echo "    Verifica que los nodos K3s tengan ruta a 10.40.1.0/24"
    exit 1
  fi
done

# ── Verificar conectividad con PG HA Cluster ──────────────────────────────────
echo "→ Verificando conectividad con PG HA..."
PG_NODES=("192.168.0.127" "192.168.0.186" "192.168.0.226")
for pg_ip in "${PG_NODES[@]}"; do
  if nc -z -w3 "${pg_ip}" 5002 2>/dev/null; then
    echo "  ✓ ${pg_ip}:5002 (PgBouncer) OK"
  else
    echo "  ⚠ ${pg_ip}:5002 no responde — verificar después de instalar K3s"
  fi
done

echo ""
echo "  ✅ 00-prepare-node completado en ${NODE_NAME}"
