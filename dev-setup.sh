#!/usr/bin/env bash
# =============================================================================
# dev-setup.sh — Bootstrap local K3s dev environment on WSL
#
# Usage:
#   chmod +x dev-setup.sh
#   ./dev-setup.sh
#
# What it does:
#   1. Installs K3s (single-node cluster) if not already installed
#   2. Waits for the cluster to be healthy
#   3. Builds the portal image locally and imports it into K3s
#   4. Applies all K8s manifests (except Cloudflare tunnel)
#   5. Applies dev-only secret overrides
#   6. Prints access info
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$REPO_ROOT/k8s"
PORTAL_DIR="$REPO_ROOT/portal"
ADDON_DIR="$REPO_ROOT/odoo_k8s_saas"

PORTAL_IMAGE="saas-portal:dev"
ODOO_IMAGE="odoo:18"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 1. Install K3s ───────────────────────────────────────────────────────────
if ! command -v k3s &>/dev/null; then
  info "Installing K3s …"
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable=traefik --write-kubeconfig-mode=644" sh -
  sleep 5
else
  info "K3s already installed: $(k3s --version | head -1)"
fi

# Make kubectl use the local kubeconfig
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

info "Waiting for K3s node to be Ready …"
timeout 120 bash -c 'until kubectl get nodes 2>/dev/null | grep -q "Ready"; do sleep 3; done'
kubectl get nodes

# ── 2. Build portal image and import into K3s ────────────────────────────────
info "Building portal image: $PORTAL_IMAGE …"
docker build -t "$PORTAL_IMAGE" "$PORTAL_DIR"

info "Importing portal image into K3s containerd …"
docker save "$PORTAL_IMAGE" | sudo k3s ctr images import -

# ── 3. Create namespaces ─────────────────────────────────────────────────────
info "Applying namespace manifest …"
kubectl apply -f "$K8S_DIR/00-namespace.yaml"

# ── 4. Apply dev secrets (overrides production values) ───────────────────────
info "Applying dev secrets …"
kubectl apply -f "$K8S_DIR/dev/00-dev-secrets.yaml"

# ── 5. Apply Postgres (postgres:16) ──────────────────────────────────────────
info "Applying Postgres 16 …"
kubectl apply -f "$K8S_DIR/02-postgres.yaml"

# ── 6. Apply RBAC ────────────────────────────────────────────────────────────
info "Applying RBAC …"
kubectl apply -f "$K8S_DIR/04-rbac.yaml"

# ── 7. Apply Portal (patched to use local image) ─────────────────────────────
info "Applying portal (local image, imagePullPolicy=Never) …"
kubectl apply -f "$K8S_DIR/05-portal.yaml"
kubectl -n aeisoftware patch deployment portal \
  --type=json \
  -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/image","value":"'"$PORTAL_IMAGE"'"},
    {"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}
  ]'

# Patch portal API_KEY to match dev value
kubectl -n aeisoftware set env deployment/portal API_KEY="dev-api-key-local"

# ── 8. Apply Odoo admin ───────────────────────────────────────────────────────
info "Applying Odoo admin deployment …"
kubectl apply -f "$K8S_DIR/06-odoo-admin.yaml"

# ── 9. Expose services locally via NodePort (dev only) ───────────────────────
info "Exposing Odoo and Portal as NodePort services …"

kubectl -n aeisoftware expose deployment portal \
  --name=portal-nodeport \
  --type=NodePort \
  --port=8000 \
  --target-port=8000 \
  --dry-run=client -o yaml | \
  kubectl apply -f - 2>/dev/null || true

kubectl -n odoo-admin expose deployment odoo-admin \
  --name=odoo-nodeport \
  --type=NodePort \
  --port=8069 \
  --target-port=8069 \
  --dry-run=client -o yaml | \
  kubectl apply -f - 2>/dev/null || true

# ── 10. Wait for pods ────────────────────────────────────────────────────────
info "Waiting for Postgres …"
kubectl -n aeisoftware rollout status statefulset/postgres --timeout=120s

info "Waiting for Portal …"
kubectl -n aeisoftware rollout status deployment/portal --timeout=120s

info "Waiting for Odoo admin …"
kubectl -n odoo-admin rollout status deployment/odoo-admin --timeout=180s

# ── 11. Print access info ────────────────────────────────────────────────────
WSL_IP=$(hostname -I | awk '{print $1}')
ODOO_PORT=$(kubectl -n odoo-admin get svc odoo-nodeport -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "?")
PORTAL_PORT=$(kubectl -n aeisoftware get svc portal-nodeport -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "?")

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Local K3s dev environment is ready!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Odoo Admin:   http://${WSL_IP}:${ODOO_PORT}"
echo -e "  Portal API:   http://${WSL_IP}:${PORTAL_PORT}/docs"
echo ""
echo -e "  API key (dev): dev-api-key-local"
echo -e "  DB password:   DevPass2026!"
echo ""
echo -e "  kubectl alias: export KUBECONFIG=/etc/rancher/k3s/k3s.yaml"
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
