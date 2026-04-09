"""
tests/test_manifests.py

Tests unitarios de k8s_utils/manifests.py.
No requieren cluster ni Postgres.
"""
from __future__ import annotations
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def manifests_mod():
    """Import manifests module fresh each test."""
    import importlib
    import k8s_utils.manifests as m
    importlib.reload(m)
    return m


# ── namespace_manifest ────────────────────────────────────────────────────────

class TestNamespaceManifest:
    def test_name_is_odoo_prefixed(self, manifests_mod):
        m = manifests_mod.namespace_manifest("acme")
        assert m["metadata"]["name"] == "odoo-acme"

    def test_labels_contain_managed_by(self, manifests_mod):
        m = manifests_mod.namespace_manifest("acme")
        assert m["metadata"]["labels"]["managed-by"] == "saas-portal"

    def test_plan_in_labels(self, manifests_mod):
        m = manifests_mod.namespace_manifest("acme", plan="pro")
        assert m["metadata"]["labels"]["plan"] == "pro"

    def test_annotations_set(self, manifests_mod):
        m = manifests_mod.namespace_manifest("acme", plan="enterprise", odoo_version="17.0")
        ann = m["metadata"]["annotations"]
        assert ann["saas-portal/plan"] == "enterprise"
        assert ann["saas-portal/odoo-version"] == "17.0"
        assert "saas-portal/created-at" in ann

    def test_default_plan_is_starter(self, manifests_mod):
        m = manifests_mod.namespace_manifest("acme")
        assert m["metadata"]["annotations"]["saas-portal/plan"] == "starter"


# ── secret_manifest ───────────────────────────────────────────────────────────

class TestSecretManifest:
    def test_namespace_matches(self, manifests_mod):
        m = manifests_mod.secret_manifest("demo", "dbpass", "adminpass", "apppass")
        assert m["metadata"]["namespace"] == "odoo-demo"

    def test_keys_present(self, manifests_mod):
        m = manifests_mod.secret_manifest("demo", "dbpass", "adminpass", "apppass")
        assert set(m["data"].keys()) == {"DB_PASSWORD", "ADMIN_PASSWD", "APP_ADMIN_PASSWORD"}

    def test_values_are_base64(self, manifests_mod):
        import base64
        m = manifests_mod.secret_manifest("demo", "mypassword", "admin", "app")
        decoded = base64.b64decode(m["data"]["DB_PASSWORD"]).decode()
        assert decoded == "mypassword"

    def test_secret_type_is_opaque(self, manifests_mod):
        m = manifests_mod.secret_manifest("demo", "p", "a", "ap")
        assert m["type"] == "Opaque"


# ── configmap_manifest ────────────────────────────────────────────────────────

class TestConfigmapManifest:
    def test_db_name_in_conf(self, manifests_mod):
        m = manifests_mod.configmap_manifest("tenant1", "pw", "admin")
        conf = m["data"]["odoo.conf"]
        assert "odoo_tenant1" in conf

    def test_db_user_in_conf(self, manifests_mod):
        m = manifests_mod.configmap_manifest("tenant1", "pw", "admin")
        conf = m["data"]["odoo.conf"]
        assert "odoo-tenant1" in conf

    def test_workers_in_conf(self, manifests_mod):
        m = manifests_mod.configmap_manifest("tenant1", "pw", "admin")
        assert "workers = 2" in m["data"]["odoo.conf"]

    def test_addons_json_default_empty(self, manifests_mod):
        import json
        m = manifests_mod.configmap_manifest("tenant1", "pw", "admin")
        addons = json.loads(m["data"]["addons.json"])
        assert addons == []

    def test_addons_json_with_repos(self, manifests_mod):
        import json
        repos = [{"url": "https://github.com/test/repo.git", "branch": "18.0"}]
        m = manifests_mod.configmap_manifest("tenant1", "pw", "admin", addons_repos=repos)
        parsed = json.loads(m["data"]["addons.json"])
        assert parsed[0]["url"] == repos[0]["url"]

    def test_proxy_mode_enabled(self, manifests_mod):
        m = manifests_mod.configmap_manifest("tenant1", "pw", "admin")
        assert "proxy_mode = True" in m["data"]["odoo.conf"]


# ── ingress_manifest ──────────────────────────────────────────────────────────

class TestIngressManifest:
    def test_host_uses_base_domain(self, manifests_mod):
        m = manifests_mod.ingress_manifest("mycompany")
        rules = m["spec"]["rules"]
        assert len(rules) == 1
        assert rules[0]["host"].startswith("mycompany.")

    def test_https_entrypoint(self, manifests_mod):
        m = manifests_mod.ingress_manifest("mycompany")
        annotations = m["metadata"]["annotations"]
        assert "websecure" in annotations.get(
            "traefik.ingress.kubernetes.io/router.entrypoints", ""
        )

    def test_tls_configured(self, manifests_mod):
        m = manifests_mod.ingress_manifest("mycompany")
        assert "tls" in m["spec"]
        assert len(m["spec"]["tls"]) == 1

    def test_websocket_path_exists(self, manifests_mod):
        m = manifests_mod.ingress_manifest("mycompany")
        paths = m["spec"]["rules"][0]["http"]["paths"]
        path_paths = [p["path"] for p in paths]
        assert "/websocket" in path_paths
        assert "/" in path_paths

    def test_websocket_uses_port_8072(self, manifests_mod):
        m = manifests_mod.ingress_manifest("mycompany")
        paths = m["spec"]["rules"][0]["http"]["paths"]
        ws_path = next(p for p in paths if p["path"] == "/websocket")
        assert ws_path["backend"]["service"]["port"]["number"] == 8072


# ── deployment_manifest ───────────────────────────────────────────────────────

class TestDeploymentManifest:
    def test_uses_custom_image_when_given(self, manifests_mod):
        m = manifests_mod.deployment_manifest("demo", custom_image="my.registry/odoo:custom")
        containers = m["spec"]["template"]["spec"]["containers"]
        assert containers[0]["image"] == "my.registry/odoo:custom"

    def test_uses_default_image_when_none(self, manifests_mod):
        m = manifests_mod.deployment_manifest("demo", odoo_version="18.0", custom_image=None)
        containers = m["spec"]["template"]["spec"]["containers"]
        assert "odoo:18.0" in containers[0]["image"]

    def test_readiness_probe_present(self, manifests_mod):
        m = manifests_mod.deployment_manifest("demo")
        containers = m["spec"]["template"]["spec"]["containers"]
        assert "readinessProbe" in containers[0]

    def test_init_containers_present(self, manifests_mod):
        m = manifests_mod.deployment_manifest("demo")
        init_containers = m["spec"]["template"]["spec"]["initContainers"]
        assert len(init_containers) >= 1

    def test_resource_limits_present(self, manifests_mod):
        m = manifests_mod.deployment_manifest("demo")
        resources = m["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert "limits" in resources and "requests" in resources

    def test_strategy_is_recreate(self, manifests_mod):
        m = manifests_mod.deployment_manifest("demo")
        assert m["spec"]["strategy"]["type"] == "Recreate"


# ── all_manifests ─────────────────────────────────────────────────────────────

class TestAllManifests:
    def test_returns_all_required_kinds(self, manifests_mod):
        manifests = manifests_mod.all_manifests(
            tenant_id="test",
            db_password="db",
            admin_password="adm",
            app_admin_password="app",
        )
        kinds = [m["kind"] for m in manifests]
        for expected in ["Namespace", "NetworkPolicy", "PersistentVolumeClaim",
                         "Secret", "ConfigMap", "Deployment", "Service", "Ingress"]:
            assert expected in kinds, f"Missing kind: {expected}"

    def test_plan_passed_to_namespace(self, manifests_mod):
        manifests = manifests_mod.all_manifests(
            tenant_id="corp",
            db_password="p",
            admin_password="a",
            app_admin_password="ap",
            plan="enterprise",
        )
        ns = next(m for m in manifests if m["kind"] == "Namespace")
        assert ns["metadata"]["annotations"]["saas-portal/plan"] == "enterprise"

    def test_all_namespaced_resources_have_correct_namespace(self, manifests_mod):
        manifests = manifests_mod.all_manifests(
            tenant_id="myco",
            db_password="p",
            admin_password="a",
            app_admin_password="ap",
        )
        for m in manifests:
            if m["kind"] != "Namespace":
                ns = m.get("metadata", {}).get("namespace")
                assert ns == "odoo-myco", f"Wrong namespace in {m['kind']}: {ns}"
