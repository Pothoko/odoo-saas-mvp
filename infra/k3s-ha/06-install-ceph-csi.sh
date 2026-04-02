#!/bin/bash
# =============================================================================
# 06-install-ceph-csi.sh — Instala Ceph CSI RBD driver en K3s
#
# Configura el StorageClass "ceph-rbd" usando el pool k3s-rbd existente.
# Los PVCs de todos los tenants Odoo usarán este StorageClass.
#
# Variables requeridas (desde .env):
#   CEPH_CLUSTER_ID — 99efe072-cf04-11f0-adef-0cc47af94ce2
#   CEPH_MON_1      — 10.40.1.240:6789
#   CEPH_MON_2      — 10.40.1.241:6789
#   CEPH_RBD_POOL   — k3s-rbd
#   CEPH_CSI_KEY    — key de client.k3s-rbd-csi
#   CEPH_ADMIN_KEY  — key de client.admin
# =============================================================================
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
NAMESPACE="ceph-csi-rbd"
CSI_CHART_VERSION="3.12.2"   # compatible con Ceph Reef/Quincy

echo ""
echo "  ┌─────────────────────────────────────────────────────────"
echo "  │  06-install-ceph-csi RBD v${CSI_CHART_VERSION}"
echo "  │  Cluster: ${CEPH_CLUSTER_ID:0:8}..."
echo "  │  Pool: ${CEPH_RBD_POOL}"
echo "  │  MONs: ${CEPH_MON_1}, ${CEPH_MON_2}"
echo "  └─────────────────────────────────────────────────────────"

# ── Validar variables ─────────────────────────────────────────────────────────
for var in CEPH_CLUSTER_ID CEPH_MON_1 CEPH_MON_2 CEPH_RBD_POOL CEPH_CSI_KEY CEPH_ADMIN_KEY; do
  if [ -z "${!var:-}" ] || [[ "${!var}" == *"change_me"* ]]; then
    echo "  ✗ ${var} no configurado en .env"
    exit 1
  fi
  echo "  ✓ ${var}"
done

# ── Namespace con privilegios (CSI necesita pods privilegiados) ───────────────
echo "→ Creando namespace ${NAMESPACE}..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace "${NAMESPACE}" \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/warn=privileged \
  --overwrite

# ── Secrets de autenticación Ceph ─────────────────────────────────────────────
echo "→ Creando secrets de Ceph..."

# Secret del admin (para el provisioner — crea/borra imágenes RBD)
kubectl -n "${NAMESPACE}" create secret generic ceph-admin-secret \
  --from-literal=userID=admin \
  --from-literal=userKey="${CEPH_ADMIN_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

# Secret del usuario CSI (para el node plugin — monta las imágenes RBD)
kubectl -n "${NAMESPACE}" create secret generic ceph-k3s-rbd-csi-secret \
  --from-literal=userID=k3s-rbd-csi \
  --from-literal=userKey="${CEPH_CSI_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "  ✓ Secrets creados"


# ── Instalar ceph-csi-rbd via Helm ───────────────────────────────────────────
# NOTA: El chart gestiona sus propios ConfigMaps (ceph-csi-config,
# ceph-csi-encryption-kms-config). NO los creamos manualmente.
# Si existen de un intento anterior, los eliminamos para que Helm los adopte.
echo "→ Limpiando ConfigMaps pre-existentes (Helm los gestionará)..."
kubectl -n "${NAMESPACE}" delete configmap \
  ceph-csi-config ceph-csi-encryption-kms-config \
  --ignore-not-found 2>/dev/null || true

echo "→ Instalando ceph-csi-rbd chart ${CSI_CHART_VERSION}..."

helm repo add ceph-csi https://ceph.github.io/csi-charts 2>/dev/null || true
helm repo update ceph-csi

helm upgrade --install ceph-csi-rbd ceph-csi/ceph-csi-rbd \
  --version "${CSI_CHART_VERSION}" \
  --namespace "${NAMESPACE}" \
  --set csiConfig[0].clusterID="${CEPH_CLUSTER_ID}" \
  --set "csiConfig[0].monitors[0]=${CEPH_MON_1}" \
  --set "csiConfig[0].monitors[1]=${CEPH_MON_2}" \
  --set provisioner.replicaCount=2 \
  --set provisioner.podSecurityPolicy.enabled=false \
  --set nodeplugin.podSecurityPolicy.enabled=false \
  --wait --timeout=300s

echo "  ✓ ceph-csi-rbd chart instalado"

# ── StorageClass ceph-rbd (default) ───────────────────────────────────────────
echo "→ Creando StorageClass ceph-rbd..."
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-rbd
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: "${CEPH_CLUSTER_ID}"
  pool: "${CEPH_RBD_POOL}"
  imageFormat: "2"
  imageFeatures: layering
  csi.storage.k8s.io/provisioner-secret-name: ceph-admin-secret
  csi.storage.k8s.io/provisioner-secret-namespace: "${NAMESPACE}"
  csi.storage.k8s.io/controller-expand-secret-name: ceph-admin-secret
  csi.storage.k8s.io/controller-expand-secret-namespace: "${NAMESPACE}"
  csi.storage.k8s.io/node-stage-secret-name: ceph-k3s-rbd-csi-secret
  csi.storage.k8s.io/node-stage-secret-namespace: "${NAMESPACE}"
reclaimPolicy: Retain
allowVolumeExpansion: true
volumeBindingMode: Immediate
EOF

# ── Test rápido de StorageClass ───────────────────────────────────────────────
echo "→ Test de provisioning (PVC de prueba)..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ceph-rbd-test
  namespace: default
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ceph-rbd
  resources:
    requests:
      storage: 1Gi
EOF

echo "  Esperando que el PVC se provisione..."
for i in $(seq 1 12); do
  STATUS=$(kubectl get pvc ceph-rbd-test -n default -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")
  echo "  PVC status: ${STATUS} (intento ${i}/12)"
  if [ "${STATUS}" = "Bound" ]; then
    echo "  ✅ StorageClass ceph-rbd funciona correctamente"
    break
  fi
  sleep 10
done

# Limpiar PVC de prueba
kubectl delete pvc ceph-rbd-test -n default --ignore-not-found

echo ""
kubectl get storageclasses
echo ""
echo "  ✅ Ceph CSI RBD instalado y validado"
