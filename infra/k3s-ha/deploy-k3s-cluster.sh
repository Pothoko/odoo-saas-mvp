#!/bin/bash
# =============================================================================
# deploy-k3s-cluster.sh — Orquestador del clúster K3s HA
#
# Despliega el stack completo K3s HA en los 3 nodos de OpenStack.
# Ejecutar desde tu máquina local (no desde las VMs).
#
# Orden de despliegue:
#   1. Preparar los 3 nodos
#   2. Instalar K3s server-1 (cluster-init)
#   3. Instalar kube-vip (VIP 192.168.0.150)
#   4. Instalar Cilium CNI
#   5. Unir server-2 y server-3
#   6. Instalar Traefik
#   7. Instalar Ceph CSI (StorageClass ceph-rbd)
#
# Prerequisito:
#   cp infra/k3s-ha/.env.example infra/k3s-ha/.env
#   nano infra/k3s-ha/.env   # completar K3S_TOKEN, CEPH_CSI_KEY, CEPH_ADMIN_KEY
#   ./infra/k3s-ha/deploy-k3s-cluster.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║   K3s HA Cluster — Despliegue Automatizado              ║"
echo "  ║   3 nodos control-plane · Cilium · kube-vip · Ceph RBD  ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── SSH Config ──────────────────────────────────────────────────────────────
SSH_KEY="/home/fisbert/.ssh/id_rsa"
SSH_USER="ubuntu"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o ServerAliveInterval=30"

# ─── Nodos: name:ssh_ip:internal_ip ──────────────────────────────────────────
NODES=(
  "k3s-1:10.40.2.158:192.168.0.185"   # k3s-control-1 / blade02
  "k3s-2:10.40.2.153:192.168.0.211"   # k3s-control-2 / blade01
  "k3s-3:10.40.2.159:192.168.0.243"   # k3s-control-3 / blade03
)

# El primer nodo es el que inicializa el clúster
IFS=':' read -r FIRST_NAME FIRST_SSH FIRST_IP <<< "${NODES[0]}"

# ─── Cargar .env ──────────────────────────────────────────────────────────────
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
  echo "❌ Archivo .env no encontrado."
  echo "   Copia la plantilla y completa las credenciales:"
  echo "   cp ${SCRIPT_DIR}/.env.example ${SCRIPT_DIR}/.env"
  echo "   nano ${SCRIPT_DIR}/.env"
  exit 1
fi
set -a; source "${SCRIPT_DIR}/.env"; set +a
echo "→ Variables cargadas desde .env"

# ─── Generar K3S_TOKEN si no está definido ────────────────────────────────────
if [ -z "${K3S_TOKEN:-}" ] || [[ "${K3S_TOKEN}" == "change_me" ]]; then
  K3S_TOKEN="$(openssl rand -hex 32)"
  sed -i "s/^K3S_TOKEN=.*/K3S_TOKEN=${K3S_TOKEN}/" "${SCRIPT_DIR}/.env"
  echo "→ K3S_TOKEN generado y guardado en .env"
fi

# ─── Validar variables críticas ──────────────────────────────────────────────
echo "→ Validando configuración..."
REQUIRED=(KUBE_VIP_IP K3S_INTERFACE CEPH_CLUSTER_ID CEPH_MON_1 CEPH_MON_2 CEPH_RBD_POOL CEPH_CSI_KEY CEPH_ADMIN_KEY)
for var in "${REQUIRED[@]}"; do
  if [ -z "${!var:-}" ] || [[ "${!var}" == *"change_me"* ]]; then
    echo "  ✗ ${var} no configurado en .env"
    exit 1
  fi
  echo "  ✓ ${var}"
done

# ─── Helper: ejecutar script remotamente ─────────────────────────────────────
run_remote() {
  local name="$1"
  local ssh_ip="$2"
  local internal_ip="$3"
  local script="$4"

  echo ""
  echo "  ┌────────────────────────────────────────────"
  echo "  │ ${script} → ${name} (${ssh_ip})"
  echo "  └────────────────────────────────────────────"

  local env_exports
  env_exports="export NODE_NAME='${name}';"
  env_exports+="export NODE_IP='${internal_ip}';"
  env_exports+="export K3S_TOKEN='${K3S_TOKEN}';"
  env_exports+="export KUBE_VIP_IP='${KUBE_VIP_IP}';"
  env_exports+="export K3S_INTERFACE='${K3S_INTERFACE}';"
  env_exports+="export CEPH_CLUSTER_ID='${CEPH_CLUSTER_ID}';"
  env_exports+="export CEPH_MON_1='${CEPH_MON_1}';"
  env_exports+="export CEPH_MON_2='${CEPH_MON_2}';"
  env_exports+="export CEPH_RBD_POOL='${CEPH_RBD_POOL}';"
  env_exports+="export CEPH_CSI_KEY='${CEPH_CSI_KEY}';"
  env_exports+="export CEPH_ADMIN_KEY='${CEPH_ADMIN_KEY}';"

  # shellcheck disable=SC2029
  ssh ${SSH_OPTS} ${SSH_USER}@${ssh_ip} \
    "sudo bash -c '${env_exports} bash -s'" < "${SCRIPT_DIR}/${script}"
}

# ─── Verificar conectividad SSH ───────────────────────────────────────────────
echo ""
echo "→ Verificando conectividad SSH..."
for node in "${NODES[@]}"; do
  IFS=':' read -r name ssh_ip internal_ip <<< "${node}"
  if ssh ${SSH_OPTS} ${SSH_USER}@${ssh_ip} "echo OK" &>/dev/null; then
    echo "  ✓ ${name} (${ssh_ip})"
  else
    echo "  ✗ ${name} (${ssh_ip}) — No se puede conectar"
    echo "    Verifica: ssh -i ${SSH_KEY} ${SSH_USER}@${ssh_ip}"
    exit 1
  fi
done

START_TIME=$(date +%s)

# =============================================================================
# PASO 1: Preparar los 3 nodos (paralelo)
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 1/7: Preparando nodos (ceph-common, rbd, sysctl)"
echo "═══════════════════════════════════════════════════════════"

for node in "${NODES[@]}"; do
  IFS=':' read -r name ssh_ip internal_ip <<< "${node}"
  run_remote "${name}" "${ssh_ip}" "${internal_ip}" "00-prepare-node.sh"
done

# =============================================================================
# PASO 2: Instalar K3s en el primer nodo (cluster-init)
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 2/7: Instalando K3s server-1 (cluster-init)"
echo "  Nodo: ${FIRST_NAME} | IP: ${FIRST_IP}"
echo "═══════════════════════════════════════════════════════════"

run_remote "${FIRST_NAME}" "${FIRST_SSH}" "${FIRST_IP}" "01-install-k3s-server1.sh"

echo "→ Esperando 30s para que el API server estabilice..."
sleep 30

# =============================================================================
# PASO 3: Instalar kube-vip (VIP 192.168.0.150)
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 3/7: Instalando kube-vip (VIP ${KUBE_VIP_IP})"
echo "═══════════════════════════════════════════════════════════"

run_remote "${FIRST_NAME}" "${FIRST_SSH}" "${FIRST_IP}" "02-install-kube-vip.sh"

echo "→ Esperando 15s para que el VIP se active..."
sleep 15

# =============================================================================
# PASO 4: Instalar Cilium CNI
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 4/7: Instalando Cilium CNI (eBPF kube-proxy replacement)"
echo "═══════════════════════════════════════════════════════════"

run_remote "${FIRST_NAME}" "${FIRST_SSH}" "${FIRST_IP}" "04-install-cilium.sh"

echo "→ Esperando 20s para que Cilium propague el CNI..."
sleep 20

# =============================================================================
# PASO 5: Unir server-2 y server-3
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 5/7: Uniendo server-2 y server-3 al clúster"
echo "═══════════════════════════════════════════════════════════"

for i in 1 2; do   # índices 1 y 2 (server-2 y server-3)
  IFS=':' read -r name ssh_ip internal_ip <<< "${NODES[$i]}"
  run_remote "${name}" "${ssh_ip}" "${internal_ip}" "03-join-k3s-servers.sh"
  echo "→ Esperando 30s antes del siguiente nodo..."
  sleep 30
done

echo ""
echo "→ Verificando estado del clúster..."
ssh ${SSH_OPTS} ${SSH_USER}@${FIRST_SSH} \
  "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get nodes -o wide"

# =============================================================================
# PASO 6: Instalar Traefik
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 6/7: Instalando Traefik v3"
echo "═══════════════════════════════════════════════════════════"

run_remote "${FIRST_NAME}" "${FIRST_SSH}" "${FIRST_IP}" "05-install-traefik.sh"

# =============================================================================
# PASO 7: Instalar Ceph CSI RBD
# =============================================================================
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PASO 7/7: Instalando Ceph CSI RBD (pool: ${CEPH_RBD_POOL})"
echo "═══════════════════════════════════════════════════════════"

run_remote "${FIRST_NAME}" "${FIRST_SSH}" "${FIRST_IP}" "06-install-ceph-csi.sh"

# =============================================================================
# RESUMEN FINAL
# =============================================================================
END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))

echo ""
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║              ✅ CLÚSTER K3s HA DESPLEGADO               ║"
echo "  ╠══════════════════════════════════════════════════════════╣"
echo "  ║                                                          ║"
echo "  ║  Tiempo total: $(printf '%02d:%02d:%02d' $((ELAPSED/3600)) $(((ELAPSED%3600)/60)) $((ELAPSED%60)))                              ║"
echo "  ║                                                          ║"
echo "  ║  Nodos:                                                  ║"
echo "  ║    k3s-control-1  192.168.0.185 (blade02)               ║"
echo "  ║    k3s-control-2  192.168.0.211 (blade01)               ║"
echo "  ║    k3s-control-3  192.168.0.243 (blade03)               ║"
echo "  ║                                                          ║"
echo "  ║  API Server VIP: https://192.168.0.150:6443             ║"
echo "  ║  Ingress:        http/https://192.168.0.150             ║"
echo "  ║  StorageClass:   ceph-rbd (pool: ${CEPH_RBD_POOL})         ║"
echo "  ║                                                          ║"
echo "  ║  Siguiente paso: Aplicar manifests K8s                  ║"
echo "  ║    cp infra/k3s-ha/.env.kubeconfig ~/.kube/k3s-ha.yaml  ║"
echo "  ║    ./infra/apply-manifests.sh                           ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Extraer kubeconfig apuntando al VIP ────────────────────────────────────
echo "→ Descargando kubeconfig (apunta al VIP ${KUBE_VIP_IP})..."
ssh ${SSH_OPTS} ${SSH_USER}@${FIRST_SSH} \
  "sudo cat /etc/rancher/k3s/k3s.yaml" | \
  sed "s/127.0.0.1/${KUBE_VIP_IP}/g" > "${SCRIPT_DIR}/.kubeconfig"
chmod 600 "${SCRIPT_DIR}/.kubeconfig"
echo "  ✅ Guardado en: ${SCRIPT_DIR}/.kubeconfig"
echo "     Para usar: export KUBECONFIG=${SCRIPT_DIR}/.kubeconfig"
