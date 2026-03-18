# Odoo SaaS MVP

Single-server Kubernetes SaaS provisioning for Odoo 18, running on **K3s + Cloudflare tunnels**.

## Architecture

```
Internet → Cloudflare Tunnel → Traefik (K3s ingress)
                                    ├── admin.aeisoftware.com  → odoo-admin pod (namespace: odoo-admin)
                                    └── <tenant>.aeisoftware.com → per-tenant Odoo pod (namespace: odoo-<tenant>)
                                              ↓
                                    Shared PostgreSQL (namespace: aeisoftware)
```

Each tenant gets:
- Dedicated namespace `odoo-<tenant_id>`
- Dedicated PVC for `/var/lib/odoo` (local-path storage)
- Isolated database `odoo_<tenant_id>` on the shared Postgres
- Traefik Ingress at `<tenant_id>.aeisoftware.com`

---

## Day 0 — Fresh Server Setup

> **Prerequisites:** Ubuntu/Debian VM with root access, a Cloudflare tunnel token (`CLOUDFLARE_TUNNEL_TOKEN`).

### Step 1 — Clone the repo

```bash
cd /opt
git clone https://github.com/jpvargassoruco/odoo-saas-mvp.git
cd odoo-saas-mvp
```

### Step 2 — Create your secrets file

```bash
cp .secrets.env.example .secrets.env
nano .secrets.env          # fill in all values — never commit this file
```

Required variables in `.secrets.env`:

| Variable | Description |
|---|---|
| `DB_PASSWORD` | Postgres password for the `odoo` user |
| `ADMIN_PASSWD` | Odoo master password |
| `API_KEY` | Secret key for the SaaS portal API |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token from your Cloudflare tunnel dashboard |

### Step 3 — Install K3s (without built-in Traefik)

```bash
bash infra/install-k3s.sh
```

Waits until node is `Ready`.

### Step 4 — Install Traefik via Helm

```bash
bash infra/install-traefik.sh
```

### Step 5 — Apply all manifests

```bash
bash infra/apply-manifests.sh
```

This will:
1. Create namespaces `aeisoftware` and `odoo-admin`
2. Create all secrets from `.secrets.env` (no secrets in git)
3. Apply `k8s/00-namespace.yaml` through `k8s/06-odoo-admin.yaml`
4. Wait for Postgres to be ready

### Step 6 — Install Odoo custom modules

After Postgres and the odoo-admin pod are running:

```bash
ODOO_POD=$(kubectl get pod -n odoo-admin -l app=odoo-admin -o name | head -1 | sed 's|pod/||')

kubectl exec -n odoo-admin "$ODOO_POD" -- \
  odoo -u odoo_k8s_saas,odoo_k8s_saas_subscription \
  -d admin --stop-after-init --no-http
```

After this, refresh your browser. The **SaaS** app will appear on the Odoo home screen.

---

## Day 1 — Provision a Tenant

```bash
curl -X POST http://portal.aeisoftware.com/api/v1/instances \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "demo", "plan": "starter", "storage_gi": 10}'

# Poll until ready
curl -H "X-API-Key: $API_KEY" http://portal.aeisoftware.com/api/v1/instances/demo
```

The instance becomes available at `https://demo.aeisoftware.com`.

---

## Updating Custom Modules (after code changes)

When you push changes to `odoo_k8s_saas` or `odoo_k8s_saas_subscription`, the pod gets the latest code
automatically via the `copy-addon` init container on the next restart. After restarting:

```bash
# 1. Restart the pod (triggers git clone of latest code)
kubectl rollout restart deployment/odoo-admin -n odoo-admin
kubectl rollout status deployment/odoo-admin -n odoo-admin

# 2. Run the database update
ODOO_POD=$(kubectl get pod -n odoo-admin -l app=odoo-admin -o name | head -1 | sed 's|pod/||')
kubectl exec -n odoo-admin "$ODOO_POD" -- \
  odoo -u odoo_k8s_saas,odoo_k8s_saas_subscription \
  -d admin --stop-after-init --no-http

# 3. Hard-refresh the browser (Ctrl+Shift+R)
```

---

## Teardown — Remove Everything

### Remove only the Odoo/portal workloads (keep K3s)

```bash
kubectl delete namespace odoo-admin aeisoftware --ignore-not-found
# Remove all tenant namespaces
kubectl get ns -o name | grep '^namespace/odoo-' | xargs -r kubectl delete
```

### Remove K3s completely (full teardown)

```bash
# This wipes K3s, all pods, ALL data, and Kubernetes state
/usr/local/bin/k3s-uninstall.sh
```

> ⚠️ **This is destructive.** All PVCs, databases, and cluster state are permanently deleted.
> PostgreSQL data lives in a PVC backed by local-path on the node's disk — it is gone after this.

### Full teardown + clean repo state

```bash
/usr/local/bin/k3s-uninstall.sh
rm -rf /opt/odoo-saas-mvp
# Re-clone and start from Day 0
```

---

## Repository Structure

```
odoo-saas-mvp/
├── k8s/                              # Kubernetes manifests
│   ├── 00-namespace.yaml             # Namespaces (aeisoftware, odoo-admin)
│   ├── 01-secrets.yaml               # Placeholder only — secrets applied from .secrets.env
│   ├── 01-traefik.yaml               # Traefik CRDs / IngressRoutes
│   ├── 02-postgres.yaml              # Shared PostgreSQL StatefulSet
│   ├── 02-cloudflare-tunnel.yaml     # Cloudflare tunnel deployment
│   ├── 03-cloudflared.yaml           # cloudflared daemonset
│   ├── 03-traefik-middleware.yaml    # Traefik middlewares
│   ├── 04-rbac.yaml                  # ServiceAccount + ClusterRole for portal
│   ├── 05-portal.yaml                # SaaS portal API (FastAPI)
│   └── 06-odoo-admin.yaml            # Admin Odoo instance + init container (git clone addons)
├── portal/                           # FastAPI portal
│   ├── main.py
│   ├── routers/instances.py          # POST/GET/DELETE /api/v1/instances
│   ├── k8s_utils/
│   │   ├── manifests.py              # Manifest generator for tenant pods
│   │   └── client.py                 # kubernetes SDK wrapper
│   ├── Dockerfile
│   └── requirements.txt
├── odoo_k8s_saas/                    # Odoo addon — admin UI for SaaS instances
│   ├── models/saas_instance.py       # saas.instance model (states, cron, K8s sync)
│   ├── views/saas_instance_views.xml # Kanban, form, list, menu, actions
│   ├── data/ir_cron.xml              # Cron: refresh instance status every 2 min
│   ├── data/mail_template.xml
│   ├── data/product_category.xml
│   └── security/ir.model.access.csv
├── odoo_k8s_saas_subscription/       # Odoo addon — subscription bridge module
│   ├── models/saas_instance.py       # Extends saas.instance with plan/subscription link
│   ├── views/                        # Extended kanban, subscription menus, portal
│   ├── data/ir_cron.xml              # Cron: suspend overdue instances daily
│   ├── data/subscription_templates.xml
│   └── security/ir.model.access.csv
├── infra/
│   ├── install-k3s.sh               # Install K3s without built-in Traefik
│   ├── install-traefik.sh           # Install Traefik via Helm
│   ├── apply-manifests.sh           # Apply all k8s manifests (reads .secrets.env)
│   └── create-cf-route.sh           # Helper for Cloudflare route creation
├── .secrets.env.example              # Template — copy to .secrets.env and fill in
├── .gitignore                        # .secrets.env and .secrets.env.* excluded
└── .github/workflows/
    └── build-portal.yaml            # Build + push portal image on push to main
```

---

## GitHub Actions CI

Set these **repository secrets** in GitHub:
- `VM_HOST` — IP or hostname of the VM
- `VM_SSH_KEY` — SSH private key for `root@VM_HOST`

On every push to `main` (touching `portal/`):
1. Builds the portal Docker image
2. Pushes to `ghcr.io/<owner>/odoo-saas-mvp/portal:latest`
3. SSHes into the VM and runs `kubectl rollout restart deployment/portal`

---

## Cloudflare Tunnel

The tunnel uses a wildcard rule:
```
*.aeisoftware.com → http://traefik.kube-system.svc.cluster.local:80
```

No per-tenant DNS changes are needed.  
Per-tenant Traefik `IngressRoute` objects route traffic by `Host:` header.

---

## Admin Odoo

Access at `https://admin.aeisoftware.com`  
The `odoo_k8s_saas` and `odoo_k8s_saas_subscription` addons provide:
- **SaaS app** on the home screen (with icon and kanban)
- Instance states: `draft → provisioning → running → suspended → terminated`
- Subscription plan linking (Starter / Growth / Enterprise)
- Suspend / Resume buttons with K8s scale-down/up
- Cron jobs for status sync and overdue-instance suspension
