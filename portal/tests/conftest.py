"""
tests/conftest.py

Fixtures compartidos para toda la suite de tests del portal.
Mockea K8s SDK y psycopg2 para que los tests no necesiten
un cluster real ni una base de datos.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Asegurar que el código fuente del portal esté en el path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Mocks de módulos externos antes de importar la app ────────────────────────

# Mockear kubernetes SDK globalmente
_k8s_mock = MagicMock()
sys.modules.setdefault("kubernetes", _k8s_mock)
sys.modules.setdefault("kubernetes.client", _k8s_mock.client)
sys.modules.setdefault("kubernetes.config", _k8s_mock.config)

# Mockear psycopg2
_pg_mock = MagicMock()
sys.modules.setdefault("psycopg2", _pg_mock)

# Mockear slowapi (puede no estar instalado en el entorno de test aislado)
_slowapi_mock = MagicMock()
_slowapi_mock.Limiter.return_value = MagicMock()
_slowapi_errors = MagicMock()
_slowapi_errors.RateLimitExceeded = Exception
sys.modules.setdefault("slowapi", _slowapi_mock)
sys.modules.setdefault("slowapi.util", MagicMock())
sys.modules.setdefault("slowapi.errors", _slowapi_errors)

# Mockear python-json-logger
sys.modules.setdefault("pythonjsonlogger", MagicMock())
sys.modules.setdefault("pythonjsonlogger.jsonlogger", MagicMock())

# ── Variables de entorno para tests ──────────────────────────────────────────
# IMPORTANTE: usar asignación directa (=), no setdefault.
# El contenedor Docker ya tiene API_KEY=dev-api-key-local; si usamos setdefault
# no lo sobreescribimos y los tests fallan con 403.
os.environ["API_KEY"]                  = "test-api-key"
os.environ["POSTGRES_HOST"]            = "localhost"
os.environ["POSTGRES_PORT"]            = "5432"
os.environ["POSTGRES_ADMIN_USER"]      = "postgres"
os.environ["POSTGRES_ADMIN_PASSWORD"]  = "test"
os.environ["BASE_DOMAIN"]              = "test.example.com"
os.environ["POSTGRES_HOST_K8S"]        = "localhost"
os.environ["POSTGRES_PORT_K8S"]        = "5432"
os.environ["POSTGRES_PORT_PRIMARY_K8S"]= "5432"
os.environ["LOG_LEVEL"]                = "WARNING"  # silencia logs durante tests
os.environ["CORS_ORIGINS"]             = "*"


# ── FastAPI test client ────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def app():
    """Import and return the FastAPI app instance."""
    from main import app as _app
    return _app


@pytest.fixture()
def client(app):
    """Synchronous TestClient for the portal app."""
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def auth_headers():
    """Headers with valid API key."""
    return {"X-API-Key": "test-api-key"}


# ── K8s mock helpers ──────────────────────────────────────────────────────────

def make_namespace_mock(name: str, labels: dict = None, annotations: dict = None):
    """Build a mock K8s Namespace object."""
    from datetime import datetime, timezone
    ns = MagicMock()
    ns.metadata.name = name
    ns.metadata.labels = labels or {"managed-by": "saas-portal", "tenant": name.removeprefix("odoo-")}
    ns.metadata.annotations = annotations or {}
    ns.metadata.creation_timestamp = datetime.now(timezone.utc)
    return ns


def make_pod_mock(phase: str = "Running", ready: bool = True):
    """Build a mock K8s Pod object."""
    pod = MagicMock()
    pod.status.phase = phase
    container_status = MagicMock()
    container_status.ready = ready
    pod.status.container_statuses = [container_status]
    pod.metadata.name = "odoo-12345678-abcde"
    return pod


@pytest.fixture()
def mock_k8s_ok(monkeypatch):
    """
    Patch k8s_utils.client functions to return healthy responses.

    IMPORTANT: functions imported at the top of routers/instances.py with
    'from k8s_utils.client import X' must be patched on the ROUTER module
    (routers.instances.X), not on the source (k8s_utils.client.X).
    Inline imports (inside functions) are patched on the source module.
    """
    # ── Top-level imports in routers/instances.py → patch on router ──
    monkeypatch.setattr("routers.instances.apply_manifest",    lambda m: None)
    monkeypatch.setattr("routers.instances.delete_namespace",  lambda ns: None)
    monkeypatch.setattr("routers.instances.annotate_namespace",lambda ns, ann: None)
    monkeypatch.setattr("routers.instances.get_namespace_annotations", lambda ns: {
        "saas-portal/plan": "starter",
        "saas-portal/odoo-version": "18.0",
        "saas-portal/created-at": "2026-01-15T00:00:00+00:00",
    })
    monkeypatch.setattr("routers.instances.get_deployment_status", lambda ns, name="odoo": {
        "phase": "Running",
        "ready": True,
    })
    monkeypatch.setattr("routers.instances.list_tenant_namespaces", lambda: [
        {
            "name": "odoo-acme",
            "annotations": {
                "saas-portal/plan": "pro",
                "saas-portal/odoo-version": "18.0",
                "saas-portal/created-at": "2026-01-10T00:00:00+00:00",
            },
            "labels": {"managed-by": "saas-portal", "tenant": "acme"},
            "created_at": "2026-01-10T00:00:00+00:00",
        }
    ])
    monkeypatch.setattr("routers.instances.get_pod_resource_usage", lambda ns: {})

    # ── Inline imports → patch on source module ──
    monkeypatch.setattr("k8s_utils.client.namespace_exists",  lambda ns: False)
    monkeypatch.setattr("k8s_utils.client.scale_deployment",  lambda ns, name, rep: None)
    monkeypatch.setattr("k8s_utils.client.read_namespaced_config_map", lambda ns, name: {})
    monkeypatch.setattr("k8s_utils.client.patch_namespaced_config_map", lambda ns, name, data: None)
    monkeypatch.setattr("k8s_utils.client.restart_deployment", lambda ns, name="odoo": None)
    monkeypatch.setattr("k8s_utils.client.read_namespaced_pod_log", lambda ns, label, lines: "OK")
    return monkeypatch


@pytest.fixture()
def mock_pg_ok(monkeypatch):
    """Patch Postgres helpers to succeed silently."""
    monkeypatch.setattr("routers.instances._create_pg_user", lambda user, pw, db: None)
    monkeypatch.setattr("routers.instances._drop_pg_user",   lambda user, db: None)
    monkeypatch.setattr("routers.instances._get_user_count", lambda tid: 3)
    return monkeypatch
