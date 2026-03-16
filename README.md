# Odoo SaaS MVP

Single-server Kubernetes SaaS provisioning for Odoo 18, running on K3s + Cloudflare tunnels.

## Architecture

```
Internet → Cloudflare tunnel → Traefik (K3s) → per-tenant Odoo pods
                                              → shared PostgreSQL
```

Each tenant gets:
- Dedicated namespace `odoo-<tenant_id>`
- Dedicated PVC for `/var/lib/odoo`
- Shared PostgreSQL with isolated database `odoo_<tenant_id>`
- Traefik Ingress at `<tenant_id>.aeisoftware.com`

## Quick Start

### 1. Install K3s on the VM
```bash
# On the Hetzner VM as root:
bash infra/install-k3s.sh
```

### 2. Set secrets
Edit `k8s/01-secrets.yaml` to fill in base64-encoded values:
```bash
echo -n "MyDBPassword" | base64    # for POSTGRES_PASSWORD
echo -n "MyAPIKey"    | base64    # for API_KEY
```

### 3. Apply all manifests
```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml  # or ~/.kube/config
bash infra/apply-manifests.sh
```

### 4. Provision a tenant
```bash
curl -X POST http://portal.aeisoftware.com/api/v1/instances \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "demo", "plan": "starter", "storage_gi": 10}'

# Poll until ready
curl -H "X-API-Key: $API_KEY" http://portal.aeisoftware.com/api/v1/instances/demo
```

The instance is available at `https://demo.aeisoftware.com`.

## Repository Structure

```
odoo-saas-mvp/
├── k8s/                        # Kubernetes manifests
│   ├── 00-namespace.yaml       # Main aeisoftware namespace
│   ├── 01-secrets.yaml         # Postgres + portal + cloudflare secrets
│   ├── 02-postgres.yaml        # Shared PostgreSQL StatefulSet
│   ├── 03-cloudflared.yaml     # Cloudflare tunnel daemon
│   ├── 04-rbac.yaml            # ServiceAccount + ClusterRole for portal
│   ├── 05-portal.yaml          # SaaS portal API deployment
│   └── 06-odoo-admin.yaml      # Admin Odoo instance
├── portal/                     # FastAPI portal
│   ├── main.py
│   ├── routers/instances.py    # POST/GET/DELETE /api/v1/instances
│   ├── k8s_utils/
│   │   ├── manifests.py        # Manifest generator (no Ceph/S3)
│   │   └── client.py           # kubernetes SDK wrapper
│   ├── Dockerfile
│   └── requirements.txt
├── odoo_k8s_saas/              # Odoo addon for admin UI
│   ├── models/saas_instance.py
│   ├── views/saas_instance_views.xml
│   ├── data/ir_cron.xml
│   └── security/ir.model.access.csv
├── infra/
│   ├── install-k3s.sh
│   ├── apply-manifests.sh
│   └── create-cf-route.sh
└── .github/workflows/
    └── build-portal.yaml       # Build + push portal image on push
```

## GitHub Actions CI

Set these **repository secrets**:
- `VM_HOST` — IP or hostname of the VM
- `VM_SSH_KEY` — SSH private key for `root@VM_HOST`

On every push to `main` (touching `portal/`):
1. Builds portal Docker image
2. Pushes to `ghcr.io/<owner>/odoo-saas-mvp/portal:latest`
3. SSHes into VM and runs `kubectl rollout restart deployment/portal`

## Cloudflare Tunnel

The tunnel is pre-created with a wildcard rule:
```
*.aeisoftware.com → http://traefik.kube-system.svc.cluster.local:80
```

No per-tenant DNS or tunnel config changes are needed.
Per-tenant Traefik Ingress rules route based on the `Host:` header.

## Admin Odoo

Access at `https://admin.aeisoftware.com` — has the `odoo_k8s_saas` addon installed for managing tenant instances via a clean tree/form UI.
