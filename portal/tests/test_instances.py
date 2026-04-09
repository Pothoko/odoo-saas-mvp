"""
tests/test_instances.py

Tests de los endpoints del router de instancias.
Usa el TestClient de FastAPI con mocks de K8s y Postgres.
"""
from __future__ import annotations
import pytest


AUTH = {"X-API-Key": "test-api-key"}


# =============================================================================
# GET /api/v1/instances  — list
# =============================================================================
class TestListInstances:
    def test_returns_list(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.get("/api/v1/instances", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_tenant_fields_present(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.get("/api/v1/instances", headers=AUTH)
        assert resp.status_code == 200
        tenants = resp.json()
        if tenants:
            t = tenants[0]
            for field in ("tenant_id", "namespace", "url", "status", "plan"):
                assert field in t, f"Missing field: {field}"

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/instances")
        # APIKeyHeader devuelve 403 en la mayoría de versiones de FastAPI,
        # pero algunas versiones devuelven 401. Ambos son correctos.
        assert resp.status_code in (401, 403)


# =============================================================================
# GET /api/v1/instances/{id}  — get single
# =============================================================================
class TestGetInstance:
    def test_returns_instance_when_found(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.get("/api/v1/instances/acme", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "acme"

    def test_returns_404_when_not_found(self, client, mock_pg_ok, monkeypatch):
        monkeypatch.setattr(
            "routers.instances.get_deployment_status",
            lambda ns, name="odoo": {"phase": "NotFound", "ready": False}
        )
        monkeypatch.setattr("routers.instances.get_namespace_annotations", lambda ns: {})
        monkeypatch.setattr("routers.instances.get_pod_resource_usage", lambda ns: {})
        resp = client.get("/api/v1/instances/nonexistent", headers=AUTH)
        assert resp.status_code == 404

    def test_status_ready_when_pod_ready(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.get("/api/v1/instances/acme", headers=AUTH)
        assert resp.json()["status"] == "ready"

    def test_status_provisioning_when_pod_not_ready(self, client, mock_pg_ok, monkeypatch):
        monkeypatch.setattr(
            "routers.instances.get_deployment_status",
            lambda ns, name="odoo": {"phase": "Running", "ready": False}
        )
        monkeypatch.setattr("routers.instances.get_namespace_annotations", lambda ns: {
            "saas-portal/plan": "starter",
            "saas-portal/odoo-version": "18.0",
            "saas-portal/created-at": "2026-01-01T00:00:00+00:00",
        })
        monkeypatch.setattr("routers.instances.get_pod_resource_usage", lambda ns: {})
        resp = client.get("/api/v1/instances/acme", headers=AUTH)
        assert resp.json()["status"] == "provisioning"

    def test_url_contains_tenant_id(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.get("/api/v1/instances/myco", headers=AUTH)
        assert "myco" in resp.json()["url"]


# =============================================================================
# POST /api/v1/instances  — create
# =============================================================================
class TestCreateInstance:
    def test_creates_successfully(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={
            "tenant_id": "newco",
            "plan": "starter",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["tenant_id"] == "newco"
        assert data["status"] == "provisioning"

    def test_returns_app_admin_password(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={"tenant_id": "corp2"})
        assert resp.status_code == 202
        assert resp.json()["app_admin_password"] is not None

    def test_rejects_duplicate_tenant(self, client, mock_pg_ok, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: True)
        resp = client.post("/api/v1/instances", headers=AUTH, json={"tenant_id": "existing"})
        assert resp.status_code == 409

    def test_invalid_tenant_id_format(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={"tenant_id": "INVALID_ID!"})
        assert resp.status_code == 422

    def test_invalid_tenant_id_too_short(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={"tenant_id": "a"})
        assert resp.status_code == 422

    def test_invalid_plan_rejected(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={
            "tenant_id": "validone",
            "plan": "invalid-plan",
        })
        assert resp.status_code == 422

    def test_invalid_storage_rejected(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={
            "tenant_id": "validone",
            "storage_gi": 9999,
        })
        assert resp.status_code == 422

    def test_rollback_on_k8s_failure(self, client, mock_pg_ok, monkeypatch):
        """When K8s provisioning fails, Postgres resources should be rolled back."""
        dropped = []
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: False)
        monkeypatch.setattr("routers.instances.annotate_namespace", lambda ns, ann: None)
        def _raise_on_apply(m):
            raise Exception("K8s API timeout")
        monkeypatch.setattr("routers.instances.apply_manifest", _raise_on_apply)
        monkeypatch.setattr(
            "routers.instances._drop_pg_user",
            lambda user, db: dropped.append(user)
        )
        resp = client.post("/api/v1/instances", headers=AUTH, json={"tenant_id": "failco"})
        assert resp.status_code == 500
        assert "failco" in str(dropped), "Rollback was not called for failed tenant"

    def test_pro_plan_accepted(self, client, mock_k8s_ok, mock_pg_ok):
        resp = client.post("/api/v1/instances", headers=AUTH, json={
            "tenant_id": "procompany",
            "plan": "pro",
        })
        assert resp.status_code == 202
        assert resp.json()["plan"] == "pro"


# =============================================================================
# DELETE /api/v1/instances/{id}
# =============================================================================
class TestDeleteInstance:
    def test_deletes_successfully(self, client, mock_pg_ok, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: True)
        monkeypatch.setattr("routers.instances.delete_namespace", lambda ns: None)
        resp = client.delete("/api/v1/instances/oldco", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "terminating"

    def test_returns_404_if_not_exists(self, client, mock_pg_ok, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: False)
        resp = client.delete("/api/v1/instances/ghost", headers=AUTH)
        assert resp.status_code == 404

    def test_pg_error_is_reported_without_blocking(self, client, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: True)
        monkeypatch.setattr("routers.instances.delete_namespace", lambda ns: None)
        def _raise_pg(u, d):
            raise Exception("PG unavailable")
        monkeypatch.setattr("routers.instances._drop_pg_user", _raise_pg)
        resp = client.delete("/api/v1/instances/badpg", headers=AUTH)
        # Should still return 200 (namespace deleted), but report pg_error
        assert resp.status_code == 200
        assert resp.json()["pg_cleanup"] == "failed"


# =============================================================================
# POST /api/v1/instances/{id}/stop|start
# =============================================================================
class TestStartStopInstance:
    def test_stop_returns_suspended(self, client, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.scale_deployment", lambda ns, name, rep: None)
        resp = client.post("/api/v1/instances/myco/stop", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

    def test_start_returns_starting(self, client, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.scale_deployment", lambda ns, name, rep: None)
        resp = client.post("/api/v1/instances/myco/start", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["status"] == "starting"


# =============================================================================
# GET /api/v1/instances/check/{id}
# =============================================================================
class TestCheckAvailability:
    def test_available_returns_true(self, client, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: False)
        # mock PG conn to always say not taken
        import routers.instances as ri
        monkeypatch.setattr(ri, "_pg_conn", lambda dbname="postgres": _mock_pg_conn_empty())
        resp = client.get("/api/v1/instances/check/newid", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["available"] is True

    def test_namespace_taken_makes_unavailable(self, client, monkeypatch):
        monkeypatch.setattr("k8s_utils.client.namespace_exists", lambda ns: True)
        import routers.instances as ri
        monkeypatch.setattr(ri, "_pg_conn", lambda dbname="postgres": _mock_pg_conn_empty())
        resp = client.get("/api/v1/instances/check/taken", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["available"] is False
        assert resp.json()["namespace_exists"] is True


# =============================================================================
# GET /api/v1/instances/{id}/logs
# =============================================================================
class TestLogs:
    def test_returns_logs(self, client, monkeypatch):
        monkeypatch.setattr(
            "k8s_utils.client.read_namespaced_pod_log",
            lambda ns, app_label, tail_lines: "2026-01-01 INFO Starting..."
        )
        resp = client.get("/api/v1/instances/myco/logs", headers=AUTH)
        assert resp.status_code == 200
        assert "logs" in resp.json()
        assert "Starting" in resp.json()["logs"]

    def test_lines_param_forwarded(self, client, monkeypatch):
        received_lines = []
        def capture(ns, label, lines):
            received_lines.append(lines)
            return "ok"
        monkeypatch.setattr("k8s_utils.client.read_namespaced_pod_log", capture)
        client.get("/api/v1/instances/myco/logs?lines=500", headers=AUTH)
        assert received_lines and received_lines[0] == 500


# =============================================================================
# GET /healthz
# =============================================================================
class TestHealth:
    def test_healthz_no_auth(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_healthz_has_version(self, client):
        resp = client.get("/healthz")
        assert "version" in resp.json()


# =============================================================================
# Helpers
# =============================================================================
def _mock_pg_conn_empty():
    """Return a mock psycopg2 connection that reports no DB exists."""
    from unittest.mock import MagicMock, patch

    conn = MagicMock()
    conn.autocommit = True
    cur = MagicMock()
    cur.__enter__ = lambda s: cur
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = None  # DB/namespace not found
    conn.cursor.return_value = cur
    return conn
