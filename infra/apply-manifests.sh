#!/usr/bin/env bash
# =============================================================================
# infra/apply-manifests.sh
# Apply all K8s manifests in order, injecting secrets from .secrets.env.
#
# Usage (production):
#   ./infra/apply-manifests.sh
#
# Usage (dry-run — shows what would be applied, touches nothing):
#   ./infra/apply-manifests.sh --dry-run
#
# Secrets are read from .secrets.env (gitignored, never committed).
# Copy .secrets.env.example → .secrets.env and fill in real values first.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_FILE="$REPO_ROOT/.secrets.env"
DRY_RUN=false

# ── Argument parsing ─────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

KUBECTL_ARGS=""
if $DRY_RUN; then
  echo "==> DRY RUN mode — no changes will be made to the cluster"
  KUBECTL_ARGS="--dry-run=client"
fi

# ── Load secrets ─────────────────────────────────────────────────────────────
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo ""
  echo "ERROR: $SECRETS_FILE not found."
  echo ""
  echo "  Create it from the example:"
  echo "    cp .secrets.env.example .secrets.env"
  echo "    # edit .secrets.env and fill in real passwords"
  echo ""
  exit 1
fi

# shellcheck source=/dev/null
set -o allexport
source "$SECRETS_FILE"
set +o allexport

# Validate required variables are set and not placeholders
missing=()
for var in DB_PASSWORD ADMIN_PASSWD API_KEY; do
  val="${!var:-}"
  if [[ -z "$val" || "$val" == "change_me" ]]; then
    missing+=("$var")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo ""
  echo "ERROR: The following secrets are missing or still set to 'change_me' in $SECRETS_FILE:"
  for v in "${missing[@]}"; do echo "  - $v"; done
  echo ""
  exit 1
fi

# ── Apply secrets first (from env vars, never from git files) ────────────────
echo "==> Applying secrets from .secrets.env …"
cat <<EOF | kubectl apply $KUBECTL_ARGS -f -
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: aeisoftware
type: Opaque
stringData:
  POSTGRES_PASSWORD: "${DB_PASSWORD}"
---
apiVersion: v1
kind: Secret
metadata:
  name: portal-secret
  namespace: aeisoftware
type: Opaque
stringData:
  API_KEY: "${API_KEY}"
---
apiVersion: v1
kind: Secret
metadata:
  name: portal-secret
  namespace: odoo-admin
type: Opaque
stringData:
  API_KEY: "${API_KEY}"
---
apiVersion: v1
kind: Secret
metadata:
  name: odoo-admin-secret
  namespace: odoo-admin
type: Opaque
stringData:
  DB_PASSWORD: "${DB_PASSWORD}"
  ADMIN_PASSWD: "${ADMIN_PASSWD}"
EOF

# Apply Cloudflare tunnel token if set
if [[ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" && "${CLOUDFLARE_TUNNEL_TOKEN}" != "change_me" ]]; then
  echo "==> Applying cloudflare-secret …"
  cat <<EOF | kubectl apply $KUBECTL_ARGS -f -
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-secret
  namespace: aeisoftware
type: Opaque
stringData:
  TUNNEL_TOKEN: "${CLOUDFLARE_TUNNEL_TOKEN}"
EOF
fi

# ── Apply all other manifests (secrets files are deliberately skipped) ────────
echo "==> Applying manifests …"
for f in "$REPO_ROOT"/k8s/0*.yaml; do
  filename=$(basename "$f")

  # Skip 01-secrets.yaml — it is now a placeholder-only file.
  # All secrets were already applied above from .secrets.env.
  if [[ "$filename" == "01-secrets.yaml" ]]; then
    echo "  skipping $filename (secrets applied from .secrets.env above)"
    continue
  fi

  echo "  applying $f …"
  kubectl apply $KUBECTL_ARGS -f "$f"
done

# ── Wait for core services ────────────────────────────────────────────────────
if ! $DRY_RUN; then
  echo "==> Waiting for postgres to be ready …"
  kubectl -n aeisoftware rollout status statefulset/postgres --timeout=120s

  echo ""
  echo "==> All manifests applied successfully."
  echo ""
  echo "    Portal:     http://portal.aeisoftware.com"
  echo "    Admin Odoo: http://admin.aeisoftware.com"
fi
