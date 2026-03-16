#!/usr/bin/env bash
# infra/apply-manifests.sh
# Apply all K8s manifests in order. Run from repo root.
# Requires kubectl pointed at the target cluster.
set -euo pipefail

echo "==> Applying manifests …"
for f in k8s/0*.yaml; do
  echo "  applying $f …"
  kubectl apply -f "$f"
done

echo "==> Waiting for postgres to be ready …"
kubectl -n aeisoftware rollout status statefulset/postgres --timeout=120s

echo "==> All manifests applied."
echo ""
echo "    Portal: http://portal.aeisoftware.com"
echo "    Admin Odoo: http://admin.aeisoftware.com"
