"""
routers/instances.py

REST API for tenant lifecycle.
State is embedded in K8s objects (namespace labels/annotations).
No S3/boto3/Ceph required.
"""
from __future__ import annotations
import logging
import os
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
import re

from k8s_utils.manifests import all_manifests, BASE_DOMAIN, POSTGRES_HOST, POSTGRES_PORT
from k8s_utils.client import (
    apply_manifest,
    delete_namespace,
    get_deployment_status,
    list_tenant_namespaces,
    annotate_namespace,
    get_namespace_annotations,
    get_pod_resource_usage,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Postgres superuser used only by the portal to create/drop tenant users
_PG_ADMIN_USER = os.getenv("POSTGRES_ADMIN_USER", "postgres")
_PG_ADMIN_PASSWORD = os.getenv("POSTGRES_ADMIN_PASSWORD", "")


# ── schemas ───────────────────────────────────────────────────────────────────

class CreateInstanceRequest(BaseModel):
    tenant_id: str            # slug: letters, numbers, hyphens
    plan: str = "starter"     # starter | pro | enterprise
    storage_gi: int = 10
    addons_repos: list = []
    odoo_version: str = "18.0"
    custom_image: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$", v):
            raise ValueError("tenant_id must be lowercase alphanumeric/hyphens, 2-32 chars")
        return v

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        if v not in ("starter", "pro", "enterprise"):
            raise ValueError("plan must be 'starter', 'pro' or 'enterprise'")
        return v

    @field_validator("storage_gi")
    @classmethod
    def validate_storage(cls, v: int) -> int:
        if not (1 <= v <= 500):
            raise ValueError("storage_gi must be between 1 and 500")
        return v


class InstanceResponse(BaseModel):
    tenant_id: str
    namespace: str
    url: str
    status: str
    plan: str = "starter"
    odoo_version: str = "18.0"
    created_at: Optional[str] = None
    user_count: int = 0
    cpu_millicores: Optional[int] = None
    memory_mib: Optional[int] = None
    app_admin_password: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    odoo_conf: Optional[str] = None
    addons_repos: Optional[list] = None


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/check/{tenant_id}")
def check_availability(tenant_id: str):
    """Check whether a tenant_id is available (namespace + DB don't exist)."""
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import namespace_exists
    ns_taken = namespace_exists(namespace)

    db_name = f"odoo_{tenant_id}"
    db_taken = False
    try:
        conn = _pg_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            db_taken = cur.fetchone() is not None
        conn.close()
    except Exception:
        pass  # If PG is unreachable, only check namespace

    available = not ns_taken and not db_taken
    return {
        "tenant_id": tenant_id,
        "available": available,
        "namespace_exists": ns_taken,
        "database_exists": db_taken,
    }


@router.get("", response_model=list[InstanceResponse])
def list_instances():
    """List all tenant instances managed by this portal."""
    namespaces = list_tenant_namespaces()
    results = []
    for ns_info in namespaces:
        ns_name = ns_info["name"]
        tenant_id = ns_name.removeprefix("odoo-")
        annotations = ns_info["annotations"]

        info = get_deployment_status(ns_name)
        status = "ready" if info["ready"] else ("terminating" if info["phase"] == "Terminating" else "provisioning")

        metrics = get_pod_resource_usage(ns_name)

        user_count = 0
        if status == "ready":
            user_count = _get_user_count(tenant_id)

        results.append(InstanceResponse(
            tenant_id=tenant_id,
            namespace=ns_name,
            url=f"https://{tenant_id}.{BASE_DOMAIN}",
            status=status,
            plan=annotations.get("saas-portal/plan", "starter"),
            odoo_version=annotations.get("saas-portal/odoo-version", "18.0"),
            created_at=annotations.get("saas-portal/created-at") or ns_info.get("created_at"),
            user_count=user_count,
            cpu_millicores=metrics.get("cpu_millicores") or None,
            memory_mib=metrics.get("memory_mib") or None,
        ))
    return results


@router.post("", response_model=InstanceResponse, status_code=202)
def create_instance(req: CreateInstanceRequest):
    """
    Provision a new Odoo tenant.
    1. Guard: reject duplicate tenant IDs.
    2. Creates a dedicated Postgres role + database.
    3. Applies K8s manifests.
    Rolls back Postgres resources on K8s failure.
    """
    namespace = f"odoo-{req.tenant_id}"
    from k8s_utils.client import namespace_exists
    if namespace_exists(namespace):
        raise HTTPException(
            status_code=409,
            detail=f"Tenant '{req.tenant_id}' already exists. Choose a different name.",
        )

    db_password = _gen_password()
    admin_password = _gen_password()
    app_admin_password = _gen_password(16)
    pg_user = f"odoo-{req.tenant_id}"
    db_name = f"odoo_{req.tenant_id}"

    # Step 1 — Postgres user + database
    try:
        _create_pg_user(pg_user, db_password, db_name)
    except Exception as exc:
        logger.exception("Failed to create Postgres user %s", pg_user)
        raise HTTPException(status_code=500, detail=f"Postgres setup failed: {exc}") from exc

    # Step 2 — K8s manifests (rollback PG on failure)
    manifests = all_manifests(
        tenant_id=req.tenant_id,
        db_password=db_password,
        admin_password=admin_password,
        app_admin_password=app_admin_password,
        storage_gi=req.storage_gi,
        addons_repos=req.addons_repos,
        odoo_version=req.odoo_version,
        custom_image=req.custom_image,
        plan=req.plan,
    )

    applied: list[dict] = []
    try:
        for m in manifests:
            apply_manifest(m)
            applied.append(m)
    except Exception as exc:
        logger.exception("Error applying manifest — rolling back Postgres resources")
        # Best-effort rollback: drop PG resources
        try:
            _drop_pg_user(pg_user, db_name)
        except Exception as rollback_exc:
            logger.warning("Rollback failed for PG user %s: %s", pg_user, rollback_exc)
        raise HTTPException(status_code=500, detail=f"K8s provisioning failed: {exc}") from exc

    # Step 3 — Annotate namespace with tenant metadata
    try:
        annotate_namespace(namespace, {
            "saas-portal/plan": req.plan,
            "saas-portal/odoo-version": req.odoo_version,
            "saas-portal/created-at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("Could not annotate namespace %s: %s", namespace, exc)

    return InstanceResponse(
        tenant_id=req.tenant_id,
        namespace=namespace,
        url=f"https://{req.tenant_id}.{BASE_DOMAIN}",
        status="provisioning",
        plan=req.plan,
        odoo_version=req.odoo_version,
        created_at=datetime.now(timezone.utc).isoformat(),
        app_admin_password=app_admin_password,
    )


@router.get("/{tenant_id}", response_model=InstanceResponse)
def get_instance(tenant_id: str):
    """Poll the readiness of a tenant instance."""
    namespace = f"odoo-{tenant_id}"
    info = get_deployment_status(namespace)

    if info["phase"] == "NotFound":
        raise HTTPException(status_code=404, detail=f"Instance '{tenant_id}' not found")

    status = "ready" if info["ready"] else "provisioning"
    annotations = get_namespace_annotations(namespace)
    metrics = get_pod_resource_usage(namespace)

    user_count = 0
    if status == "ready":
        user_count = _get_user_count(tenant_id)

    return InstanceResponse(
        tenant_id=tenant_id,
        namespace=namespace,
        url=f"https://{tenant_id}.{BASE_DOMAIN}",
        status=status,
        plan=annotations.get("saas-portal/plan", "starter"),
        odoo_version=annotations.get("saas-portal/odoo-version", "18.0"),
        created_at=annotations.get("saas-portal/created-at"),
        user_count=user_count,
        cpu_millicores=metrics.get("cpu_millicores") or None,
        memory_mib=metrics.get("memory_mib") or None,
    )


@router.delete("/{tenant_id}", status_code=200)
def delete_instance(tenant_id: str):
    """Delete all K8s resources for a tenant and drop Postgres resources."""
    namespace = f"odoo-{tenant_id}"

    # Verify tenant exists before attempting deletion
    from k8s_utils.client import namespace_exists
    if not namespace_exists(namespace):
        raise HTTPException(status_code=404, detail=f"Instance '{tenant_id}' not found")

    try:
        delete_namespace(namespace)
    except Exception as exc:
        logger.exception("Failed to delete namespace %s", namespace)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Drop Postgres user and database (best-effort)
    pg_user = f"odoo-{tenant_id}"
    db_name = f"odoo_{tenant_id}"
    pg_error = None
    try:
        _drop_pg_user(pg_user, db_name)
    except Exception as exc:
        logger.warning("Could not drop Postgres user %s: %s", pg_user, exc)
        pg_error = str(exc)

    return {
        "status": "terminating",
        "tenant_id": tenant_id,
        "namespace": namespace,
        "pg_cleanup": "failed" if pg_error else "ok",
        "pg_error": pg_error,
    }


@router.post("/{tenant_id}/stop")
def stop_instance(tenant_id: str):
    """Suspend a tenant instance (scale to 0)."""
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import scale_deployment
    try:
        scale_deployment(namespace, "odoo", 0)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "suspended", "tenant_id": tenant_id}


@router.post("/{tenant_id}/start")
def start_instance(tenant_id: str):
    """Resume a tenant instance (scale to 1)."""
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import scale_deployment
    try:
        scale_deployment(namespace, "odoo", 1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "starting", "tenant_id": tenant_id}


@router.get("/{tenant_id}/config")
def get_instance_config(tenant_id: str):
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import read_namespaced_config_map
    try:
        data = read_namespaced_config_map(namespace, "odoo-conf")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    import json
    addons = []
    if "addons.json" in data:
        try:
            addons = json.loads(data["addons.json"])
        except Exception as e:
            logger.warning("Could not parse addons.json for %s: %s", tenant_id, e)
    return {"odoo_conf": data.get("odoo.conf", ""), "addons_repos": addons}


@router.put("/{tenant_id}/config")
def update_instance_config(tenant_id: str, req: ConfigUpdateRequest):
    if req.odoo_conf is None:
        raise HTTPException(status_code=400, detail="odoo_conf is required for PUT")
    return patch_instance_config(tenant_id, req)


@router.patch("/{tenant_id}/config")
def patch_instance_config(tenant_id: str, req: ConfigUpdateRequest):
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import patch_namespaced_config_map, restart_deployment
    import json
    update_data = {}
    if req.odoo_conf is not None:
        update_data["odoo.conf"] = req.odoo_conf
    if req.addons_repos is not None:
        update_data["addons.json"] = json.dumps(req.addons_repos)

    if not update_data:
        return {"status": "no change"}

    try:
        patch_namespaced_config_map(namespace, "odoo-conf", update_data)
        restart_deployment(namespace, "odoo")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "restarting", "tenant_id": tenant_id}


@router.get("/{tenant_id}/logs")
def get_instance_logs(tenant_id: str, lines: int = 200):
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import read_namespaced_pod_log
    try:
        logs = read_namespaced_pod_log(namespace, "app=odoo", lines)
        return {"logs": logs, "tenant_id": tenant_id, "lines": lines}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{tenant_id}/metrics")
def get_instance_metrics(tenant_id: str):
    """Return CPU/RAM usage and user count for a tenant."""
    namespace = f"odoo-{tenant_id}"
    from k8s_utils.client import namespace_exists
    if not namespace_exists(namespace):
        raise HTTPException(status_code=404, detail=f"Instance '{tenant_id}' not found")

    metrics = get_pod_resource_usage(namespace)
    user_count = _get_user_count(tenant_id)

    return {
        "tenant_id": tenant_id,
        "user_count": user_count,
        "cpu_millicores": metrics.get("cpu_millicores"),
        "memory_mib": metrics.get("memory_mib"),
        "metrics_available": bool(metrics),
    }


# ── Postgres helpers ───────────────────────────────────────────────────────────

def _pg_conn(dbname: str = "postgres"):
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=dbname,
        user=_PG_ADMIN_USER,
        password=_PG_ADMIN_PASSWORD,
    )


def _get_user_count(tenant_id: str) -> int:
    """Connect directly to the tenant database to count active internal users."""
    db_name = f"odoo_{tenant_id}"
    try:
        conn = _pg_conn(dbname=db_name)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM res_users WHERE share=false AND active=true"
            )
            count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.warning("Could not fetch user count for %s: %s", tenant_id, e)
        return 0


def _create_pg_user(pg_user: str, password: str, db_name: str) -> None:
    """Create a dedicated Postgres role + database for a tenant (idempotent)."""
    conn = _pg_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (pg_user,))
            if cur.fetchone():
                cur.execute(f'ALTER ROLE "{pg_user}" PASSWORD %s', (password,))
                logger.info("Updated password for existing Postgres role %s", pg_user)
            else:
                cur.execute(f'CREATE ROLE "{pg_user}" LOGIN PASSWORD %s', (password,))
                logger.info("Created Postgres role %s", pg_user)

            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{pg_user}"')
                logger.info("Created Postgres database %s", db_name)
    finally:
        conn.close()


def _drop_pg_user(pg_user: str, db_name: str) -> None:
    """Drop tenant Postgres database and role.
    Terminates active connections first to avoid 'being accessed by other users' errors.
    """
    conn = _pg_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            cur.execute(f'DROP ROLE IF EXISTS "{pg_user}"')
            logger.info("Dropped Postgres role/db for %s", pg_user)
    finally:
        conn.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _gen_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
