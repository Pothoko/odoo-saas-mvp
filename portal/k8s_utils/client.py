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


def apply_manifest(manifest: dict) -> None:
    """Apply a single manifest dict to the cluster."""
    kind = manifest.get("kind")
    ns = manifest.get("metadata", {}).get("namespace")

    if kind == "Namespace":
        try:
            _core().create_namespace(body=manifest)
        except client.exceptions.ApiException as e:
            if e.status == 409:
                pass  # already exists
            else:
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
    else:
        logger.warning("apply_manifest: unhandled kind %s", kind)


def delete_namespace(namespace: str) -> None:
    try:
        _core().delete_namespace(name=namespace)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise


def get_deployment_status(namespace: str, name: str = "odoo") -> dict:
    """Return pod readiness info for a namespace."""
    try:
        pods = _core().list_namespaced_pod(namespace=namespace, label_selector="app=odoo")
        if not pods.items:
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
