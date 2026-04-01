#!/bin/bash
# =============================================================================
# validate-cluster.sh — Validación completa del clúster PostgreSQL HA
#
# Ejecutar desde cualquier nodo del clúster para verificar que todo está OK.
# Uso: sudo bash validate-cluster.sh
# =============================================================================
set -euo pipefail

PASS=0
FAIL=0
WARN=0

NODE1_IP="192.168.0.127"
NODE2_IP="192.168.0.186"
NODE3_IP="192.168.0.226"
ALL_IPS=("$NODE1_IP" "$NODE2_IP" "$NODE3_IP")

check() {
  local desc="$1"
  local cmd="$2"
  
  if eval "$cmd" &>/dev/null; then
    echo "  ✅ ${desc}"
    ((PASS++))
  else
    echo "  ❌ ${desc}"
    ((FAIL++))
  fi
}

warn() {
  local desc="$1"
  echo "  ⚠️  ${desc}"
  ((WARN++))
}

echo ""
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║     PostgreSQL HA Cluster — Validación Completa         ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── 1. etcd ─────────────────────────────────────────────────────────────────
echo "  ─── etcd Cluster ───"
check "etcd endpoint health" \
  "etcdctl endpoint health --endpoints=http://${NODE1_IP}:2379,http://${NODE2_IP}:2379,http://${NODE3_IP}:2379"

ETCD_MEMBERS=$(etcdctl member list --endpoints=http://${NODE1_IP}:2379 2>/dev/null | wc -l)
if [ "$ETCD_MEMBERS" -eq 3 ]; then
  echo "  ✅ etcd tiene 3 miembros"
  ((PASS++))
else
  echo "  ❌ etcd tiene ${ETCD_MEMBERS} miembros (esperado: 3)"
  ((FAIL++))
fi

# ─── 2. Patroni ──────────────────────────────────────────────────────────────
echo ""
echo "  ─── Patroni Cluster ───"

PATRONI_OUTPUT=$(patronictl -c /etc/patroni/patroni.yml list 2>/dev/null || echo "")
echo "$PATRONI_OUTPUT"
echo ""

# Verificar que hay exactamente 1 leader
LEADER_COUNT=$(echo "$PATRONI_OUTPUT" | grep -c "Leader" || true)
if [ "$LEADER_COUNT" -eq 1 ]; then
  echo "  ✅ Exactamente 1 Leader"
  ((PASS++))
else
  echo "  ❌ ${LEADER_COUNT} Leaders (esperado: 1)"
  ((FAIL++))
fi

# Verificar que hay 2 replicas
REPLICA_COUNT=$(echo "$PATRONI_OUTPUT" | grep -c "Replica" || true)
if [ "$REPLICA_COUNT" -eq 2 ]; then
  echo "  ✅ 2 Replicas"
  ((PASS++))
else
  echo "  ❌ ${REPLICA_COUNT} Replicas (esperado: 2)"
  ((FAIL++))
fi

# Verificar lag de replicación
for ip in "${ALL_IPS[@]}"; do
  ROLE=$(curl -sf http://${ip}:8008/ 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('role','unknown'))" 2>/dev/null || echo "unknown")
  if [ "$ROLE" = "replica" ]; then
    LAG=$(curl -sf http://${ip}:8008/ 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('xlog',{}).get('replayed_location','?'))" 2>/dev/null || echo "?")
    echo "  ℹ️  Replica ${ip}: position ${LAG}"
  fi
done

# ─── 3. PostgreSQL ───────────────────────────────────────────────────────────
echo ""
echo "  ─── PostgreSQL ───"

for ip in "${ALL_IPS[@]}"; do
  check "PostgreSQL :5432 listo en ${ip}" \
    "pg_isready -h ${ip} -p 5432 -U postgres"
done

# ─── 4. PgBouncer ────────────────────────────────────────────────────────────
echo ""
echo "  ─── PgBouncer ───"

for ip in "${ALL_IPS[@]}"; do
  check "PgBouncer :6432 listo en ${ip}" \
    "pg_isready -h ${ip} -p 6432"
done

# ─── 5. HAProxy ──────────────────────────────────────────────────────────────
echo ""
echo "  ─── HAProxy ───"

for ip in "${ALL_IPS[@]}"; do
  for port in 5000 5001 5002 7000; do
    check "HAProxy :${port} en ${ip}" \
      "ss -tlnp | grep -q ':${port} ' || nc -z ${ip} ${port}"
  done
done

# Test funcional: RW va al primary
echo ""
echo "  ─── Tests Funcionales ───"

RW_RESULT=$(PGPASSWORD="${DB_PASSWORD:-}" psql -h ${NODE1_IP} -p 5000 -U odoo -d postgres -tAc \
  "SELECT NOT pg_is_in_recovery();" 2>/dev/null || echo "error")
if [ "$RW_RESULT" = "t" ]; then
  echo "  ✅ HAProxy :5000 → Primary (pg_is_in_recovery = false)"
  ((PASS++))
else
  echo "  ❌ HAProxy :5000 no conecta al primary (resultado: ${RW_RESULT})"
  ((FAIL++))
fi

# Test: RO va a una replica
RO_RESULT=$(PGPASSWORD="${DB_PASSWORD:-}" psql -h ${NODE1_IP} -p 5001 -U odoo -d postgres -tAc \
  "SELECT pg_is_in_recovery();" 2>/dev/null || echo "error")
if [ "$RO_RESULT" = "t" ]; then
  echo "  ✅ HAProxy :5001 → Replica (pg_is_in_recovery = true)"
  ((PASS++))
else
  if [ "$RO_RESULT" = "error" ]; then
    warn "HAProxy :5001 → No hay replicas respondiendo (puede ser normal si solo el primary está up)"
  else
    echo "  ❌ HAProxy :5001 conectó al primary en vez de replica"
    ((FAIL++))
  fi
fi

# Test: PgBouncer pooled
POOL_RESULT=$(PGPASSWORD="${DB_PASSWORD:-}" psql -h ${NODE1_IP} -p 5002 -U odoo -d postgres -tAc \
  "SELECT 1;" 2>/dev/null || echo "error")
if [ "$POOL_RESULT" = "1" ]; then
  echo "  ✅ HAProxy :5002 → PgBouncer → Primary funcional"
  ((PASS++))
else
  echo "  ❌ HAProxy :5002 no funcional (resultado: ${POOL_RESULT})"
  ((FAIL++))
fi

# ─── 6. pgBackRest ───────────────────────────────────────────────────────────
echo ""
echo "  ─── pgBackRest ───"

if pgbackrest --stanza=odoo-saas info &>/dev/null; then
  echo "  ✅ pgBackRest stanza 'odoo-saas' existe"
  ((PASS++))
  pgbackrest --stanza=odoo-saas info 2>/dev/null
else
  warn "pgBackRest stanza 'odoo-saas' no encontrada (¿RadosGW configurado?)"
fi

# ─── 7. Monitoring ──────────────────────────────────────────────────────────
echo ""
echo "  ─── Monitoring ───"

check "node_exporter :9100" \
  "curl -sf http://127.0.0.1:9100/metrics | head -1"

check "postgres_exporter :9187" \
  "curl -sf http://127.0.0.1:9187/metrics | head -1"

check "Patroni API :8008" \
  "curl -sf http://127.0.0.1:8008/"

# ─── 8. Systemd Services ────────────────────────────────────────────────────
echo ""
echo "  ─── Servicios Systemd ───"

for svc in etcd patroni pgbouncer haproxy node_exporter postgres_exporter; do
  check "systemd: ${svc}" "systemctl is-active --quiet ${svc}"
done

# ─── Resumen ─────────────────────────────────────────────────────────────────
echo ""
echo "  ═══════════════════════════════════════════════════"
TOTAL=$((PASS + FAIL + WARN))
echo "  Resultados: ${PASS} ✅  ${FAIL} ❌  ${WARN} ⚠️   (${TOTAL} tests)"

if [ "$FAIL" -eq 0 ]; then
  echo ""
  echo "  🎉 ¡Clúster PostgreSQL HA operativo!"
  echo "  ═══════════════════════════════════════════════════"
  exit 0
else
  echo ""
  echo "  ⚠️  Hay ${FAIL} problemas que requieren atención."
  echo "  ═══════════════════════════════════════════════════"
  exit 1
fi
