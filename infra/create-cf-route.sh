#!/usr/bin/env bash
# infra/create-cf-route.sh
#
# Creates / updates Cloudflare tunnel ingress rules via API.
# Requires: CF_API_TOKEN, CF_ACCOUNT_ID, CF_ZONE_ID, TUNNEL_ID env vars.
#
# Usage: ./infra/create-cf-route.sh demo
#   → adds route: demo.aeisoftware.com → http://odoo.odoo-demo.svc.cluster.local:80
#     via the existing tunnel.
set -euo pipefail

TENANT_ID="${1:?Usage: $0 <tenant_id>}"
BASE_DOMAIN="${BASE_DOMAIN:-aeisoftware.com}"
HOST="${TENANT_ID}.${BASE_DOMAIN}"
SERVICE="http://odoo.odoo-${TENANT_ID}.svc.cluster.local:8069"

echo "==> Adding Cloudflare DNS CNAME for ${HOST} …"
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records" \
  -H "Authorization: Bearer ${CF_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"CNAME\",
    \"name\": \"${HOST}\",
    \"content\": \"${TUNNEL_ID}.cfargotunnel.com\",
    \"proxied\": true
  }" | jq .

# Note: tunnel ingress rules are set via the cloudflare zero trust dashboard
# or via the tunnel config file. The tunnel already has a wildcard route:
#   *.aeisoftware.com → http://traefik.kube-system.svc.cluster.local:80
# So no per-tenant API call is needed once the wildcard is in place.
echo "==> Done. DNS propagation may take 30-60 seconds."
echo "    URL: https://${HOST}"
