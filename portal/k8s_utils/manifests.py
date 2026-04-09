"""
k8s_utils/manifests.py

Generates Kubernetes manifest dicts for a tenant Odoo deployment.
Fase 2 — K3s HA con Ceph RBD storage y PostgreSQL HA externo:
  - PostgreSQL HA en 192.168.0.127/.186/.226 via HAProxy
  - :5002 PgBouncer pooled (HTTP workers)
  - :5000 HAProxy primary directo (init + longpoll)
  - ceph-rbd StorageClass (pool k3s-rbd)
  - Cilium NetworkPolicy con egress a 192.168.0.0/24
"""
from __future__ import annotations
import os
from typing import Any

BASE_DOMAIN = os.getenv("BASE_DOMAIN", "aeisoftware.com")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres.aeisoftware.svc.cluster.local")
# Host que usarán los pods de Odoo en K3s (puede diferir del host que usa el portal)
# En dev: IP del host donde corre Docker (ej. 10.91.4.18)
POSTGRES_HOST_K8S = os.getenv("POSTGRES_HOST_K8S", POSTGRES_HOST)
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5002"))          # Portal → Postgres
_default_port_k8s = os.getenv("POSTGRES_PORT_K8S") or os.getenv("POSTGRES_PORT", "5002")
POSTGRES_PORT_K8S = int(_default_port_k8s)                        # Pods → Postgres
POSTGRES_PORT_PRIMARY = int(os.getenv("POSTGRES_PORT_PRIMARY", "5000"))  # Primary directo
_default_port_primary_k8s = os.getenv("POSTGRES_PORT_PRIMARY_K8S") or os.getenv("POSTGRES_PORT_PRIMARY", "5000")
POSTGRES_PORT_PRIMARY_K8S = int(_default_port_primary_k8s)
POSTGRES_USER = os.getenv("POSTGRES_USER", "odoo")
ODOO_IMAGE = os.getenv("ODOO_IMAGE", "odoo:18")
STORAGE_CLASS_NAME = os.getenv("STORAGE_CLASS_NAME", "ceph-rbd")

ODOO_HEADERS_MIDDLEWARE = "kube-system-odoo-headers@kubernetescrd"


def namespace_manifest(tenant_id: str, plan: str = "starter", odoo_version: str = "18.0") -> dict[str, Any]:
    """Namespace for one tenant: odoo-<tenant_id>"""
    from datetime import datetime, timezone
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": _ns(tenant_id),
            "labels": {
                "managed-by": "saas-portal",
                "tenant": tenant_id,
                "plan": plan,
            },
            "annotations": {
                "saas-portal/plan": plan,
                "saas-portal/odoo-version": odoo_version,
                "saas-portal/created-at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }


def pvc_manifest(tenant_id: str, storage_gi: int = 10) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": "odoo-data",
            "namespace": _ns(tenant_id),
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": STORAGE_CLASS_NAME,
            "resources": {"requests": {"storage": f"{storage_gi}Gi"}},
        },
    }


def secret_manifest(tenant_id: str, db_password: str, admin_password: str, app_admin_password: str) -> dict[str, Any]:
    """Per-tenant secret with DB password and Odoo admin password."""
    import base64
    def b64(s: str) -> str:
        return base64.b64encode(s.encode()).decode()

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "odoo-secret",
            "namespace": _ns(tenant_id),
        },
        "type": "Opaque",
        "data": {
            "DB_PASSWORD": b64(db_password),
            "ADMIN_PASSWD": b64(admin_password),
            "APP_ADMIN_PASSWORD": b64(app_admin_password),
        },
    }


def configmap_manifest(tenant_id: str, db_password: str, admin_password: str, addons_repos: list | None = None) -> dict[str, Any]:
    """Odoo config file per tenant — passwords are embedded at provision time."""
    db_name = _dbname(tenant_id)
    addons_repos = addons_repos or []
    import json
    addons_json_str = json.dumps(addons_repos)

    conf = f"""[options]
db_host = {POSTGRES_HOST_K8S}
db_port = {POSTGRES_PORT_K8S}
db_user = odoo-{tenant_id}
db_password = {db_password}
admin_passwd = {admin_password}
db_name = {db_name}
dbfilter = ^{db_name}$
list_db = False
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons
data_dir = /var/lib/odoo
workers = 2
max_cron_threads = 1
gevent_port = 8072
proxy_mode = True
without_demo = True
"""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "odoo-conf",
            "namespace": _ns(tenant_id),
        },
        "data": {
            "odoo.conf": conf,
            "addons.json": addons_json_str
        },
    }



def deployment_manifest(tenant_id: str, odoo_version: str = "18.0", custom_image: str | None = None) -> dict[str, Any]:
    pg_user = f"odoo-{tenant_id}"
    active_image = custom_image if custom_image else f"odoo:{odoo_version}"
    # Shared volume mounts and env used by both init and main containers
    _vol_mounts = [
        {"name": "odoo-conf", "mountPath": "/etc/odoo"},
        {"name": "odoo-data", "mountPath": "/var/lib/odoo"},
        {"name": "odoo-extra-addons", "mountPath": "/mnt/extra-addons"},
    ]
    _env = [
        {"name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "odoo-secret", "key": "DB_PASSWORD"}}},
        {"name": "APP_ADMIN_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "odoo-secret", "key": "APP_ADMIN_PASSWORD"}}},
        {"name": "HOST",     "value": POSTGRES_HOST_K8S},
        {"name": "PORT",     "value": str(POSTGRES_PORT_K8S)},
        {"name": "USER",     "value": pg_user},
        {"name": "PASSWORD", "valueFrom": {"secretKeyRef": {"name": "odoo-secret", "key": "DB_PASSWORD"}}},
    ]
    # Init env usa el primary directo (5000) para --init=base (evita PgBouncer transaction mode)
    _init_env = [
        {"name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "odoo-secret", "key": "DB_PASSWORD"}}},
        {"name": "APP_ADMIN_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "odoo-secret", "key": "APP_ADMIN_PASSWORD"}}},
        {"name": "HOST",     "value": POSTGRES_HOST_K8S},
        {"name": "PORT",     "value": str(POSTGRES_PORT_PRIMARY_K8S)},
        {"name": "USER",     "value": pg_user},
        {"name": "PASSWORD", "valueFrom": {"secretKeyRef": {"name": "odoo-secret", "key": "DB_PASSWORD"}}},
    ]
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "odoo",
            "namespace": _ns(tenant_id),
            "labels": {"app": "odoo", "tenant": tenant_id},
        },
        "spec": {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": "odoo"}},
            "template": {
                "metadata": {"labels": {"app": "odoo", "tenant": tenant_id}},
                "spec": {
                    # Init container: bootstrap the DB schema (workers>0 mode can't do this)
                    "initContainers": [
                        {
                            "name": "clone-addons",
                            "image": "python:3.10-alpine",
                            "securityContext": {"runAsUser": 0, "runAsNonRoot": False},  # root para apk add
                            "command": ["/bin/sh", "-c"],
                            "args": [
                                "apk add --no-cache git && python3 -c '\n"
                                "import json, os, subprocess\n"
                                "try:\n"
                                "    with open(\"/etc/odoo/addons.json\") as f:\n"
                                "        addons = json.load(f)\n"
                                "except Exception:\n"
                                "    addons = []\n"
                                "for repo in addons:\n"
                                "    url = repo.get(\"url\")\n"
                                "    branch = repo.get(\"branch\", \"\")\n"
                                "    if not url: continue\n"
                                "    repo_name = url.rstrip(\"/\").rsplit(\"/\", 1)[-1]\n"
                                "    if repo_name.endswith(\".git\"): repo_name = repo_name[:-4]\n"
                                "    dest = f\"/mnt/extra-addons/{repo_name}\"\n"
                                "    cmd = [\"git\", \"clone\", \"--depth=1\"]\n"
                                "    if branch:\n"
                                "        cmd.extend([\"-b\", branch])\n"
                                "    cmd.extend([url, dest])\n"
                                "    print(f\"Cloning {url} branch {branch} into {dest}...\")\n"
                                "    if not os.path.exists(dest):\n"
                                "        subprocess.run(cmd, check=True)\n"
                                "'"
                            ],
                            "volumeMounts": _vol_mounts,
                        },
                        {
                            "name": "odoo-init",
                            "image": active_image,
                            "imagePullPolicy": "Always",
                            "command": ["/bin/sh", "-c"],
                            "args": [
                                "odoo --config=/etc/odoo/odoo.conf --init=base --stop-after-init && "
                                "echo \"env.ref('base.user_admin').write({'password': '${APP_ADMIN_PASSWORD}'}); env.cr.commit()\" | odoo shell --config=/etc/odoo/odoo.conf"
                            ],
                            "env": _init_env,
                            "volumeMounts": _vol_mounts,
                        }
                    ],
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 101,
                        "fsGroup": 101,
                    },
                    "containers": [
                        {
                            "name": "odoo",
                            "image": active_image,
                            "imagePullPolicy": "Always",
                            "args": ["--config=/etc/odoo/odoo.conf"],
                            "ports": [
                                {"containerPort": 8069},
                                {"containerPort": 8072},
                            ],
                            "env": _env,
                            "volumeMounts": _vol_mounts,
                            "readinessProbe": {
                                "httpGet": {"path": "/web/health", "port": 8069},
                                "initialDelaySeconds": 30,
                                "periodSeconds": 15,
                                "failureThreshold": 40,
                            },
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "512Mi"},
                                "limits":   {"cpu": "1",    "memory": "2Gi"},
                            },
                        }
                    ],
                    "volumes": [
                        {"name": "odoo-conf", "configMap": {"name": "odoo-conf"}},
                        {"name": "odoo-data", "persistentVolumeClaim": {"claimName": "odoo-data"}},
                        {"name": "odoo-extra-addons", "emptyDir": {}},
                    ],
                },
            },
        },
    }


def network_policy_manifest(tenant_id: str) -> dict[str, Any]:
    """Isolate tenant namespace: deny all, allow Traefik for 8069/8072 and Postgres for 5432."""
    ns = _ns(tenant_id)
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "tenant-isolation", "namespace": ns},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {   # Allow Ingress Controller (Traefik)
                    "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}],
                    "ports": [{"protocol": "TCP", "port": 8069}, {"protocol": "TCP", "port": 8072}]
                }
            ],
            "egress": [
                {   # Service postgres en aeisoftware (ClusterIP → Endpoints → HAProxy)
                    "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "aeisoftware"}}}],
                    "ports": [
                        {"protocol": "TCP", "port": POSTGRES_PORT},
                        {"protocol": "TCP", "port": POSTGRES_PORT_PRIMARY},
                    ]
                },
                {   # Egress directo a red PG HA (192.168.0.0/24)
                    "to": [{"ipBlock": {"cidr": "192.168.0.0/24"}}],
                    "ports": [
                        {"protocol": "TCP", "port": POSTGRES_PORT},
                        {"protocol": "TCP", "port": POSTGRES_PORT_PRIMARY},
                    ]
                },
                {   # DNS
                    "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
                    "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]
                },
                {   # GitHub addons HTTPS
                    "to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}],
                    "ports": [{"protocol": "TCP", "port": 443}]
                }
            ]
        }
    }


def service_manifest(tenant_id: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "odoo", "namespace": _ns(tenant_id)},
        "spec": {
            "selector": {"app": "odoo"},
            "ports": [
                {"name": "http", "port": 8069, "targetPort": 8069},
                {"name": "longpoll", "port": 8072, "targetPort": 8072},
            ],
        },
    }


def ingress_manifest(tenant_id: str) -> dict[str, Any]:
    """HTTPS Ingress for Traefik with websecure entrypoint."""
    subdomain = tenant_id  # e.g. demo → demo.aeisoftware.com
    host = f"{subdomain}.{BASE_DOMAIN}"
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "odoo-ingress",
            "namespace": _ns(tenant_id),
            "annotations": {
                "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
                "traefik.ingress.kubernetes.io/router.middlewares": "kube-system-odoo-headers@kubernetescrd,kube-system-odoo-compress@kubernetescrd",
                "traefik.ingress.kubernetes.io/router.tls": "true",
            },
        },
        "spec": {
            "ingressClassName": "traefik",
            "tls": [{"hosts": [host]}],
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/websocket",
                                "pathType": "Prefix",
                                "backend": {"service": {"name": "odoo", "port": {"number": 8072}}},
                            },
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {"service": {"name": "odoo", "port": {"number": 8069}}},
                            },
                        ]
                    },
                }
            ],
        },
    }


def all_manifests(
    tenant_id: str,
    db_password: str,
    admin_password: str,
    app_admin_password: str,
    storage_gi: int = 10,
    addons_repos: list | None = None,
    odoo_version: str = "18.0",
    custom_image: str | None = None,
    plan: str = "starter",
) -> list[dict]:
    """Return all manifests in apply-order."""
    return [
        namespace_manifest(tenant_id, plan=plan, odoo_version=odoo_version),
        network_policy_manifest(tenant_id),
        pvc_manifest(tenant_id, storage_gi),
        secret_manifest(tenant_id, db_password, admin_password, app_admin_password),
        configmap_manifest(tenant_id, db_password, admin_password, addons_repos or []),
        deployment_manifest(tenant_id, odoo_version, custom_image),
        service_manifest(tenant_id),
        ingress_manifest(tenant_id),
    ]



# ── helpers ──────────────────────────────────────────────────────────────────
def _ns(tenant_id: str) -> str:
    return f"odoo-{tenant_id}"


def _dbname(tenant_id: str) -> str:
    return f"odoo_{tenant_id}"
