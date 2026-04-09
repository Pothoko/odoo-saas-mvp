"""
k8s_utils/client.py

Thin wrapper around the kubernetes Python SDK.
Loads in-cluster config when running inside pods,
falls back to kubeconfig file for local dev.
"""
from __future__ import annotations
import logging
import os
from functools import lru_cache

from kubernetes import client, config as kube_config

logger = logging.getLogger(__name__)

# Label usada para identificar namespaces gestionados por este portal
MANAGED_BY_LABEL = "managed-by=saas-portal"


# ── K8s API clients ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _core() -> client.CoreV1Api:
    _load_config()
    return client.CoreV1Api()


@lru_cache(maxsize=1)
def _apps() -> client.AppsV1Api:
    _load_config()
    return client.AppsV1Api()


@lru_cache(maxsize=1)
def _networking() -> client.NetworkingV1Api:
    _load_config()
    return client.NetworkingV1Api()


def _load_config():
    try:
        kube_config.load_incluster_config()
        logger.info("Using in-cluster kubeconfig")
    except Exception:
        kube_config.load_kube_config()
        logger.info("Using local kubeconfig")


# ── Apply / Delete ────────────────────────────────────────────────────────────

def apply_manifest(manifest: dict) -> None:
    """Apply a single manifest dict to the cluster (create-or-skip-409)."""
    kind = manifest.get("kind")
    ns = manifest.get("metadata", {}).get("namespace")

    if kind == "Namespace":
        try:
            _core().create_namespace(body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "PersistentVolumeClaim":
        try:
            _core().create_namespaced_persistent_volume_claim(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "Secret":
        try:
            _core().create_namespaced_secret(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "ConfigMap":
        try:
            _core().create_namespaced_config_map(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "Deployment":
        try:
            _apps().create_namespaced_deployment(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "Service":
        try:
            _core().create_namespaced_service(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "Ingress":
        try:
            _networking().create_namespaced_ingress(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    elif kind == "NetworkPolicy":
        try:
            _networking().create_namespaced_network_policy(namespace=ns, body=manifest)
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise

    else:
        logger.warning("apply_manifest: unhandled kind %s", kind)


def delete_namespace(namespace: str) -> None:
    try:
        _core().delete_namespace(name=namespace)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise


# ── Read ──────────────────────────────────────────────────────────────────────

def get_deployment_status(namespace: str, name: str = "odoo") -> dict:
    """Return pod readiness info for a namespace."""
    try:
        pods = _core().list_namespaced_pod(namespace=namespace, label_selector="app=odoo")
        if not pods.items:
            # Namespace exists but no pods yet
            return {"phase": "Pending", "ready": False}
        pod = pods.items[0]
        phase = pod.status.phase or "Unknown"
        ready = any(
            c.ready
            for c in (pod.status.container_statuses or [])
        )
        return {"phase": phase, "ready": ready}
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return {"phase": "NotFound", "ready": False}
        raise


def namespace_exists(namespace: str) -> bool:
    """Return True if a K8s namespace already exists."""
    try:
        _core().read_namespace(name=namespace)
        return True
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return False
        raise


def list_tenant_namespaces() -> list[dict]:
    """
    Return a list of dicts with namespace metadata for every tenant namespace.
    Each dict: {"name": str, "annotations": dict, "labels": dict, "created_at": str}
    """
    try:
        ns_list = _core().list_namespace(label_selector=MANAGED_BY_LABEL)
        result = []
        for ns in ns_list.items:
            meta = ns.metadata
            result.append({
                "name": meta.name,
                "annotations": meta.annotations or {},
                "labels": meta.labels or {},
                "created_at": meta.creation_timestamp.isoformat() if meta.creation_timestamp else None,
            })
        return result
    except client.exceptions.ApiException:
        logger.warning("Could not list namespaces", exc_info=True)
        return []


def annotate_namespace(namespace: str, annotations: dict) -> None:
    """Patch a namespace's annotations with the given key-value pairs."""
    body = {"metadata": {"annotations": annotations}}
    _core().patch_namespace(name=namespace, body=body)


def get_namespace_annotations(namespace: str) -> dict:
    """Return annotations dict for a namespace, empty dict if not found."""
    try:
        ns = _core().read_namespace(name=namespace)
        return ns.metadata.annotations or {}
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return {}
        raise


def read_namespaced_config_map(namespace: str, name: str) -> dict:
    try:
        cm = _core().read_namespaced_config_map(name=name, namespace=namespace)
        return cm.data or {}
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return {}
        raise


def patch_namespaced_config_map(namespace: str, name: str, data: dict) -> None:
    _core().patch_namespaced_config_map(name=name, namespace=namespace, body={"data": data})


def read_namespaced_pod_log(
    namespace: str, app_label: str = "app=odoo", tail_lines: int = 200
) -> str:
    try:
        pods = _core().list_namespaced_pod(namespace=namespace, label_selector=app_label)
        if not pods.items:
            return "No pods found."
        pod_name = pods.items[0].metadata.name
        return _core().read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=tail_lines
        )
    except Exception as e:
        return f"Could not fetch logs: {e}"


def restart_deployment(namespace: str, name: str = "odoo") -> None:
    from datetime import datetime, timezone
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                    }
                }
            }
        }
    }
    _apps().patch_namespaced_deployment(name=name, namespace=namespace, body=body)


def scale_deployment(namespace: str, name: str, replicas: int) -> None:
    body = {"spec": {"replicas": replicas}}
    _apps().patch_namespaced_deployment_scale(name=name, namespace=namespace, body=body)


def get_pod_resource_usage(namespace: str) -> dict:
    """
    Try to get CPU/memory usage from metrics-server.
    Returns {"cpu_millicores": int, "memory_mib": int} or None if unavailable.
    Fails gracefully — metrics-server may not be installed.
    """
    try:
        from kubernetes import client as k8s_client
        api = k8s_client.CustomObjectsApi()
        metrics = api.list_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
        )
        items = metrics.get("items", [])
        if not items:
            return {}
        containers = items[0].get("containers", [])
        cpu_total = 0
        mem_total = 0
        for c in containers:
            usage = c.get("usage", {})
            cpu_str = usage.get("cpu", "0")
            mem_str = usage.get("memory", "0")
            cpu_total += _parse_cpu(cpu_str)
            mem_total += _parse_memory_mib(mem_str)
        return {"cpu_millicores": cpu_total, "memory_mib": mem_total}
    except Exception:
        # metrics-server not available or other error — non-fatal
        return {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_cpu(cpu_str: str) -> int:
    """Convert k8s CPU string ('250m', '1') to millicores."""
    if cpu_str.endswith("n"):
        return int(int(cpu_str[:-1]) / 1_000_000)
    if cpu_str.endswith("u"):
        return int(int(cpu_str[:-1]) / 1_000)
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1])
    try:
        return int(float(cpu_str) * 1000)
    except ValueError:
        return 0


def _parse_memory_mib(mem_str: str) -> int:
    """Convert k8s memory string ('512Mi', '1Gi') to MiB."""
    if mem_str.endswith("Ki"):
        return int(int(mem_str[:-2]) / 1024)
    if mem_str.endswith("Mi"):
        return int(mem_str[:-2])
    if mem_str.endswith("Gi"):
        return int(mem_str[:-2]) * 1024
    if mem_str.endswith("Ti"):
        return int(mem_str[:-2]) * 1024 * 1024
    try:
        return int(int(mem_str) / (1024 * 1024))
    except ValueError:
        return 0
