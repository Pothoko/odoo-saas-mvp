#!/bin/bash
# install-monitoring.sh
# 
# Installs a lightweight monitoring stack on K3s:
# 1. Metrics Server (for kubectl top)
# 2. Loki + Grafana (for logs)

set -e

echo "==> Checking for Helm..."
if ! command -v helm &> /dev/null; then
    echo "Helm not found. Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

echo "==> Adding Helm repos..."
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

echo "==> Installing Metrics Server (if not present)..."
# K3s usually includes metrics-server by default.
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml || true

echo "==> Installing Loki + Promtail + Grafana (Loki Stack)..."
kubectl create namespace monitoring --ignore-not-found
helm upgrade --install loki-stack grafana/loki-stack \
  --namespace monitoring \
  --set grafana.enabled=true \
  --set prometheus.enabled=false \
  --set promtail.enabled=true

echo "==> Monitoring stack installed."
echo "To get Grafana admin password:"
echo "kubectl get secret --namespace monitoring loki-stack-grafana -o jsonpath=\"{.data.admin-password}\" | base64 --decode ; echo"
echo "To forward Grafana port:"
echo "kubectl port-forward --namespace monitoring service/loki-stack-grafana 3000:80"
