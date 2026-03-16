"""
routers/instances.py

REST API for tenant lifecycle.
Avoids any S3/boto3/Ceph — state is embedded in K8s objects.
"""
from __future__ import annotations
import logging
import secrets
import string

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
import re

from ..k8s_utils.manifests import all_manifests
from ..k8s_utils.client import apply_manifest, delete_namespace, get_deployment_status

logger = logging.getLogger(__name__)
router = APIRouter()

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
    Returns immediately; poll GET /instances/{id} for readiness.
    """
    db_password = _gen_password()
    admin_password = _gen_password()

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

    from ..k8s_utils.manifests import BASE_DOMAIN
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

    from ..k8s_utils.manifests import BASE_DOMAIN
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


# ── helpers ──────────────────────────────────────────────────────────────────

def _gen_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
