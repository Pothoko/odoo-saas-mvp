#!/bin/bash
# =============================================================================
# 06-setup-monitoring.sh — Configura postgres_exporter para Prometheus
#
# node_exporter ya fue instalado y activado por 00-install-base.sh
# Este script configura postgres_exporter para métricas de PostgreSQL
#
# Variables requeridas:
#   PG_SUPERUSER_PASSWORD — Para conectar a PostgreSQL
# =============================================================================
set -euo pipefail

echo "══════════════════════════════════════════════════"
echo "  06-setup-monitoring.sh — Configurando monitoreo"
echo "══════════════════════════════════════════════════"

: "${PG_SUPERUSER_PASSWORD:?ERROR: PG_SUPERUSER_PASSWORD no definido}"

# ─── Esperar a que PostgreSQL esté listo ─────────────────────────────────────
echo "→ Esperando a que PostgreSQL esté listo..."
for i in $(seq 1 30); do
  if pg_isready -h 127.0.0.1 -p 5432 2>/dev/null; then
    break
  fi
  sleep 2
done

# ─── Configurar postgres_exporter ────────────────────────────────────────────
echo "→ Configurando postgres_exporter..."

# Crear archivo de conexión
cat > /etc/default/postgres_exporter <<EOF
DATA_SOURCE_NAME="postgresql://postgres:${PG_SUPERUSER_PASSWORD}@127.0.0.1:5432/postgres?sslmode=disable"
EOF

chmod 600 /etc/default/postgres_exporter
chown postgres_exporter:postgres_exporter /etc/default/postgres_exporter 2>/dev/null || \
  chown root:root /etc/default/postgres_exporter

# Crear queries custom para Odoo
mkdir -p /etc/postgres_exporter

cat > /etc/postgres_exporter/queries.yaml <<'QUERIES'
# Custom queries for Odoo SaaS monitoring
pg_database_size:
  query: |
    SELECT datname AS database,
           pg_database_size(datname) AS size_bytes
    FROM pg_database
    WHERE datname NOT IN ('template0', 'template1', 'postgres')
    ORDER BY size_bytes DESC
    LIMIT 50
  master: true
  metrics:
    - database:
        usage: "LABEL"
        description: "Database name"
    - size_bytes:
        usage: "GAUGE"
        description: "Database size in bytes"

pg_replication_lag:
  query: |
    SELECT
      CASE WHEN pg_is_in_recovery() THEN
        EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
      ELSE 0 END AS lag_seconds
  metrics:
    - lag_seconds:
        usage: "GAUGE"
        description: "Replication lag in seconds"

pg_connections:
  query: |
    SELECT datname AS database,
           state,
           count(*) AS count
    FROM pg_stat_activity
    WHERE datname IS NOT NULL
    GROUP BY datname, state
  master: true
  metrics:
    - database:
        usage: "LABEL"
        description: "Database name"
    - state:
        usage: "LABEL"
        description: "Connection state"
    - count:
        usage: "GAUGE"
        description: "Number of connections"

pg_long_running_queries:
  query: |
    SELECT datname AS database,
           count(*) AS count
    FROM pg_stat_activity
    WHERE state = 'active'
      AND query_start < now() - interval '1 minute'
      AND datname IS NOT NULL
    GROUP BY datname
  master: true
  metrics:
    - database:
        usage: "LABEL"
        description: "Database name"
    - count:
        usage: "GAUGE"
        description: "Number of queries running > 1 minute"

pg_locks:
  query: |
    SELECT mode,
           count(*) AS count
    FROM pg_locks
    WHERE granted
    GROUP BY mode
  master: true
  metrics:
    - mode:
        usage: "LABEL"
        description: "Lock mode"
    - count:
        usage: "GAUGE"
        description: "Number of locks held"
QUERIES

chown -R root:root /etc/postgres_exporter

# ─── Crear servicio systemd ─────────────────────────────────────────────────
echo "→ Creando servicio systemd para postgres_exporter..."

cat > /etc/systemd/system/postgres_exporter.service <<'UNIT'
[Unit]
Description=Prometheus PostgreSQL Exporter
After=network-online.target patroni.service
Wants=network-online.target

[Service]
User=postgres_exporter
Group=postgres_exporter
Type=simple
EnvironmentFile=/etc/default/postgres_exporter
ExecStart=/usr/local/bin/postgres_exporter \
  --extend.query-path=/etc/postgres_exporter/queries.yaml \
  --auto-discover-databases \
  --exclude-databases=template0,template1 \
  --web.listen-address=:9187
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# ─── Iniciar postgres_exporter ──────────────────────────────────────────────
echo "→ Iniciando postgres_exporter..."
systemctl daemon-reload
systemctl enable postgres_exporter
systemctl restart postgres_exporter

sleep 2

# ─── Verificar todos los exporters ──────────────────────────────────────────
echo ""
echo "→ Verificando exporters..."

# node_exporter
if curl -sf http://127.0.0.1:9100/metrics >/dev/null 2>&1; then
  echo "  node_exporter     :9100 ✓"
else
  echo "  node_exporter     :9100 ✗"
fi

# postgres_exporter
if curl -sf http://127.0.0.1:9187/metrics >/dev/null 2>&1; then
  echo "  postgres_exporter :9187 ✓"
else
  echo "  postgres_exporter :9187 ✗ (puede tardar unos segundos en arrancar)"
fi

# Patroni REST API
if curl -sf http://127.0.0.1:8008/ >/dev/null 2>&1; then
  echo "  Patroni API       :8008 ✓"
else
  echo "  Patroni API       :8008 ✗"
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ Monitoreo configurado"
echo ""
echo "  Endpoints de métricas:"
echo "    node_exporter     → http://<ip>:9100/metrics"
echo "    postgres_exporter → http://<ip>:9187/metrics"
echo "    Patroni           → http://<ip>:8008/"
echo "    HAProxy stats     → http://<ip>:7000/"
echo ""
echo "  Para integrarlo con Prometheus, agregar targets:"
echo "    - 192.168.0.127:9100"
echo "    - 192.168.0.127:9187"
echo "    - 192.168.0.186:9100"
echo "    - 192.168.0.186:9187"
echo "    - 192.168.0.226:9100"
echo "    - 192.168.0.226:9187"
echo "══════════════════════════════════════════════════"
