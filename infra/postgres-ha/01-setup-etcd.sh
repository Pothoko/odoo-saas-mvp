#!/bin/bash
# =============================================================================
# 01-setup-etcd.sh — Configura etcd en un nodo del clúster
#
# Variables de entorno requeridas:
#   NODE_NAME       — Nombre del nodo (pg-node1, pg-node2, pg-node3)
#   NODE_IP         — IP interna del nodo (192.168.0.x)
#
# Se ejecuta en cada VM vía SSH desde deploy-all.sh
# =============================================================================
set -euo pipefail

echo "══════════════════════════════════════════════════"
echo "  01-setup-etcd.sh — Configurando etcd"
echo "  Nodo: ${NODE_NAME} (${NODE_IP})"
echo "══════════════════════════════════════════════════"

# ─── Validar variables ──────────────────────────────────────────────────────
: "${NODE_NAME:?ERROR: NODE_NAME no definido}"
: "${NODE_IP:?ERROR: NODE_IP no definido}"

# ─── Configuración del clúster ──────────────────────────────────────────────
CLUSTER_TOKEN="odoo-saas-etcd"
CLUSTER_NAME="odoo-saas-ha"

# IPs internas de los 3 nodos (192.168.0.x)
NODE1_IP="192.168.0.127"
NODE2_IP="192.168.0.186"
NODE3_IP="192.168.0.226"

INITIAL_CLUSTER="pg-node1=http://${NODE1_IP}:2380,pg-node2=http://${NODE2_IP}:2380,pg-node3=http://${NODE3_IP}:2380"

# ─── Crear archivo de configuración de etcd ─────────────────────────────────
echo "→ Creando configuración de etcd..."

cat > /etc/etcd.conf.yml <<EOF
# etcd configuration for ${NODE_NAME}
name: '${NODE_NAME}'
data-dir: /var/lib/etcd

# Cluster communication
initial-advertise-peer-urls: http://${NODE_IP}:2380
listen-peer-urls: http://${NODE_IP}:2380

# Client access
advertise-client-urls: http://${NODE_IP}:2379
listen-client-urls: http://${NODE_IP}:2379,http://127.0.0.1:2379

# Bootstrap
initial-cluster-token: '${CLUSTER_TOKEN}'
initial-cluster: '${INITIAL_CLUSTER}'
initial-cluster-state: 'new'

# Performance tuning
heartbeat-interval: 1000
election-timeout: 5000

# Snapshots
snapshot-count: 10000
max-snapshots: 5
max-wals: 5

# Quotas
quota-backend-bytes: 2147483648  # 2GB

# Logging
log-level: info
logger: zap
EOF

chown etcd:etcd /etc/etcd.conf.yml

# ─── Limpiar datos previos si existen ────────────────────────────────────────
if [ -d /var/lib/etcd/member ]; then
  echo "→ Limpiando datos etcd previos..."
  rm -rf /var/lib/etcd/member
fi

# ─── Crear servicio systemd ─────────────────────────────────────────────────
echo "→ Creando servicio systemd para etcd..."

cat > /etc/systemd/system/etcd.service <<'UNIT'
[Unit]
Description=etcd distributed key-value store
Documentation=https://etcd.io/docs/
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=etcd
Group=etcd
EnvironmentFile=-/etc/default/etcd
ExecStart=/usr/local/bin/etcd --config-file=/etc/etcd.conf.yml
Restart=always
RestartSec=10s
LimitNOFILE=65536
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
UNIT

# ─── Iniciar etcd ───────────────────────────────────────────────────────────
echo "→ Iniciando etcd..."
systemctl daemon-reload
systemctl enable etcd
systemctl start etcd

# NO verificar health aquí: etcd necesita quórum (2/3 nodos).
# Si verificamos aquí, el nodo 1 bloqueará hasta que 2 y 3 estén corriendo.
# La verificación de quórum se hace desde deploy-all.sh después de lanzar los 3 nodos.
echo "  etcd iniciado. Esperando a que los demás nodos se unan para formar quórum..."
sleep 3

# Verificar solo que el proceso arrancó (no que tenga quórum)
if systemctl is-active --quiet etcd; then
  echo "  ✅ Proceso etcd activo en ${NODE_NAME}"
else
  echo "  ❌ etcd no pudo iniciar. Revisa: journalctl -u etcd -n 30"
  exit 1
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ etcd configurado y activo en ${NODE_NAME}"
echo "  (quórum se verificará desde deploy-all.sh)"
echo "══════════════════════════════════════════════════"
