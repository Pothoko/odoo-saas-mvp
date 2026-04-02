#!/bin/bash
# =============================================================================
# 02-install-kube-vip.sh — Despliega kube-vip DaemonSet en el clúster K3s
#
# Ejecutado en k3s-control-1 DESPUÉS de que el API server responda.
# kube-vip gestiona el VIP 192.168.0.150 via ARP (L2) para el API server.
#
# Variables:
#   KUBE_VIP_IP   — 192.168.0.150
#   K3S_INTERFACE — ens3
# =============================================================================
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
KVVERSION="v0.8.9"

echo ""
echo "  ┌─────────────────────────────────────────────────────────"
echo "  │  02-install-kube-vip"
echo "  │  VIP: ${KUBE_VIP_IP}  Interface: ${K3S_INTERFACE}"
echo "  └─────────────────────────────────────────────────────────"

# ── RBAC de kube-vip ─────────────────────────────────────────────────────────
echo "→ Aplicando RBAC de kube-vip..."
kubectl apply -f https://kube-vip.io/manifests/rbac.yaml

# ── DaemonSet de kube-vip (generado inline — sin docker requerido) ────────────
echo "→ Creando DaemonSet kube-vip ${KVVERSION}..."

cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: DaemonSet
metadata:
  labels:
    app.kubernetes.io/name: kube-vip-ds
    app.kubernetes.io/version: "${KVVERSION}"
  name: kube-vip-ds
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: kube-vip-ds
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kube-vip-ds
        app.kubernetes.io/version: "${KVVERSION}"
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: node-role.kubernetes.io/master
                    operator: Exists
              - matchExpressions:
                  - key: node-role.kubernetes.io/control-plane
                    operator: Exists
      containers:
        - args:
            - manager
          env:
            - name: vip_arp
              value: "true"
            - name: PORT
              value: "6443"
            - name: vip_interface
              value: "${K3S_INTERFACE}"
            - name: vip_cidr
              value: "32"
            - name: cp_enable
              value: "true"
            - name: cp_namespace
              value: kube-system
            - name: vip_ddns
              value: "false"
            - name: svc_enable
              value: "false"
            - name: vip_leaderelection
              value: "true"
            - name: vip_leaseduration
              value: "5"
            - name: vip_renewdeadline
              value: "3"
            - name: vip_retryperiod
              value: "1"
            - name: address
              value: "${KUBE_VIP_IP}"
            - name: prometheus_server
              value: ":2112"
          image: ghcr.io/kube-vip/kube-vip:${KVVERSION}
          imagePullPolicy: Always
          name: kube-vip
          resources:
            limits:
              cpu: 100m
              memory: 64Mi
            requests:
              cpu: 10m
              memory: 32Mi
          securityContext:
            capabilities:
              add:
                - NET_ADMIN
                - NET_RAW
      hostNetwork: true
      serviceAccountName: kube-vip
      tolerations:
        - effect: NoSchedule
          operator: Exists
        - effect: NoExecute
          operator: Exists
  updateStrategy:
    rollingUpdate:
      maxUnavailable: 1
    type: RollingUpdate
EOF

# ── Esperar que kube-vip arranque ─────────────────────────────────────────────
echo "→ Esperando DaemonSet kube-vip..."
sleep 10
kubectl -n kube-system rollout status daemonset/kube-vip-ds --timeout=60s || \
  echo "  ⚠ kube-vip-ds puede estar en NotReady (nodo normal hasta Cilium)"

# ── Verificar que el VIP está activo via ARP ──────────────────────────────────
echo "→ Verificando VIP ${KUBE_VIP_IP}..."
sleep 5
if ping -c 3 -W 2 "${KUBE_VIP_IP}" &>/dev/null; then
  echo "  ✅ VIP ${KUBE_VIP_IP} activo"
else
  echo "  ⚠ VIP no responde a ping aún — esperar 10s e intentar de nuevo"
  sleep 10
  ping -c 2 "${KUBE_VIP_IP}" &>/dev/null && echo "  ✅ VIP activo" || echo "  ⚠ VIP pendiente (normal antes de instalar Cilium)"
fi

echo ""
echo "  ✅ kube-vip instalado. Próximo paso: 04-install-cilium.sh"
echo "  (los nodos 2 y 3 se unen DESPUÉS de que Cilium esté running)"
