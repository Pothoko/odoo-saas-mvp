"""
routers/instances.py

REST API for tenant lifecycle.
Avoids any S3/boto3/Ceph — state is embedded in K8s objects.
"""
from __future__ import annotations
import logging
import os
import secrets
import string

import psycopg2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
import re

from k8s_utils.manifests import all_manifests, BASE_DOMAIN, POSTGRES_HOST, POSTGRES_PORT
from k8s_utils.client import apply_manifest, delete_namespace, get_deployment_status

logger = logging.getLogger(__name__)
router = APIRouter()

# Postgres superuser used only by the portal to create/drop tenant users
_PG_ADMIN_USER = os.getenv("POSTGRES_ADMIN_USER", "postgres")
_PG_ADMIN_PASSWORD = os.getenv("POSTGRES_ADMIN_PASSWORD", "")

# ── schemas ──────────────────────────────────────────────────────────────────

class CreateInstanceRequest(BaseModel):
    tenant_id: str          # slug: letters, numbers, hyphens
    plan: str = "starter"   # starter | pro | enterprise
    storage_gi: int = 10

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$", v):
            raise ValueError("tenant_id must be lowercase alphanumeric/hyphens, 2-32 chars")
        return v


class InstanceResponse(BaseModel):
    tenant_id: str
    namespace: str
    url: str
    status: str


# ── endpoints ────────────────────────────────────────────────────────────────

@router.post("", response_model=InstanceResponse, status_code=202)
def create_instance(req: CreateInstanceRequest):
    """
    Provision a new Odoo tenant.
    1. Creates a dedicated Postgres role + database.
    2. Applies K8s manifests (namespace, secret, configmap, deployment, …).
    Returns immediately; poll GET /instances/{id} for readiness.
    """
    # Guard: reject duplicate tenant IDs immediately
    namespace = f"odoo-{req.tenant_id}"
    from k8s_utils.client import namespace_exists
    if namespace_exists(namespace):
        raise HTTPException(
            status_code=409,
            detail=f"Tenant '{req.tenant_id}' already exists. Choose a different name.",
        )

    db_password = _gen_password()
    admin_password = _gen_password()
    pg_user = f"odoo-{req.tenant_id}"
    db_name = f"odoo_{req.tenant_id}"

    # Step 1 — Postgres user + database
    try:
        _create_pg_user(pg_user, db_password, db_name)
    except Exception as exc:
        logger.exception("Failed to create Postgres user %s", pg_user)
        raise HTTPException(status_code=500, detail=f"Postgres setup failed: {exc}") from exc

    # Step 2 — K8s manifests
    manifests = all_manifests(
        tenant_id=req.tenant_id,
        db_password=db_password,
        admin_password=admin_password,
        storage_gi=req.storage_gi,
    )

    for m in manifests:
        try:
            apply_manifest(m)
        except Exception as exc:
            logger.exception("Error applying manifest %s", m.get("kind"))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return InstanceResponse(
        tenant_id=req.tenant_id,
        namespace=f"odoo-{req.tenant_id}",
        url=f"https://{req.tenant_id}.{BASE_DOMAIN}",
        status="provisioning",
    )


@router.get("/{tenant_id}", response_model=InstanceResponse)
def get_instance(tenant_id: str):
    """Poll the readiness of a tenant instance."""
    namespace = f"odoo-{tenant_id}"
    info = get_deployment_status(namespace)

    if info["phase"] == "NotFound":
        raise HTTPException(status_code=404, detail="Instance not found")

    status = "ready" if info["ready"] else "provisioning"
    return InstanceResponse(
        tenant_id=tenant_id,
        namespace=namespace,
        url=f"https://{tenant_id}.{BASE_DOMAIN}",
        status=status,
    )


@router.delete("/{tenant_id}", status_code=204)
def delete_instance(tenant_id: str):
    """Delete all K8s resources for a tenant by deleting its namespace."""
    namespace = f"odoo-{tenant_id}"
    try:
        delete_namespace(namespace)
    except Exception as exc:
        logger.exception("Failed to delete namespace %s", namespace)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Drop Postgres user and database (best-effort; don't block the response)
    pg_user = f"odoo-{tenant_id}"
    db_name = f"odoo_{tenant_id}"
    try:
        _drop_pg_user(pg_user, db_name)
    except Exception as exc:
        logger.warning("Could not drop Postgres user %s: %s", pg_user, exc)


# ── Postgres helpers ─────────────────────────────────────────────────────────

def _pg_conn(dbname: str = "postgres"):
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=dbname,
        user=_PG_ADMIN_USER,
        password=_PG_ADMIN_PASSWORD,
    )


def _create_pg_user(pg_user: str, password: str, db_name: str) -> None:
    """Create a dedicated Postgres role + database for a tenant (idempotent)."""
    conn = _pg_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (pg_user,))
            if cur.fetchone():
                # Role exists — always sync password so K8s secret stays consistent
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
    """Drop tenant Postgres database and role."""
    conn = _pg_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            cur.execute(f'DROP ROLE IF EXISTS "{pg_user}"')
            logger.info("Dropped Postgres role/db for %s", pg_user)
    finally:
        conn.close()


# ── helpers ──────────────────────────────────────────────────────────────────

def _gen_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
