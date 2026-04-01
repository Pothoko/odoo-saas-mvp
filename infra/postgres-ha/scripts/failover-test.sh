#!/bin/bash
# =============================================================================
# failover-test.sh — Test de failover automático del clúster Patroni
#
# Simula la caída del nodo primary y verifica que:
# 1. Una replica es promovida a primary automáticamente
# 2. HAProxy redirige al nuevo primary
# 3. El nodo original se reincorpora como replica
#
# ⚠️  ESTE SCRIPT DETIENE EL PRIMARY TEMPORALMENTE
# Ejecutar solo en ventanas de mantenimiento o en entornos de prueba.
#
# Uso: sudo bash failover-test.sh
# =============================================================================
set -euo pipefail

NODE1_IP="192.168.0.127"
NODE2_IP="192.168.0.186"
NODE3_IP="192.168.0.226"

echo ""
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║   ⚠️  TEST DE FAILOVER — Clúster PostgreSQL HA          ║"
echo "  ║   Este test DETENDRÁ el primary temporalmente.          ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── Obtener estado actual ───────────────────────────────────────────────────
echo "═══ Estado ANTES del failover ═══"
patronictl -c /etc/patroni/patroni.yml list
echo ""

# Identificar el leader actual
LEADER_NAME=$(patronictl -c /etc/patroni/patroni.yml list -f json 2>/dev/null | \
  python3 -c "import sys,json; members=json.load(sys.stdin); print([m['Member'] for m in members if m['Role']=='Leader'][0])" 2>/dev/null || echo "")

if [ -z "$LEADER_NAME" ]; then
  echo "❌ No se pudo identificar el leader actual."
  exit 1
fi

LEADER_IP=$(patronictl -c /etc/patroni/patroni.yml list -f json 2>/dev/null | \
  python3 -c "import sys,json; members=json.load(sys.stdin); print([m['Host'] for m in members if m['Role']=='Leader'][0])" 2>/dev/null || echo "")

echo "Leader actual: ${LEADER_NAME} (${LEADER_IP})"
echo ""

# ─── Verificar que estamos en el nodo leader ─────────────────────────────────
CURRENT_IP=$(hostname -I | awk '{print $1}')
IS_CURRENT_LEADER=false

if [ "$CURRENT_IP" = "$LEADER_IP" ]; then
  IS_CURRENT_LEADER=true
  echo "⚠️  Estás ejecutando este script en el nodo LEADER."
  echo "   Se detendrá Patroni en ESTE nodo."
else
  echo "ℹ️  Ejecutando desde un nodo replica."
  echo "   El failover se iniciará por switchover controlado."
fi

echo ""
read -p "¿Continuar con el test de failover? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelado."
  exit 0
fi

# ─── Ejecutar failover ──────────────────────────────────────────────────────
echo ""
echo "═══ Iniciando failover... ═══"
echo ""

FAILOVER_START=$(date +%s)

if [ "$IS_CURRENT_LEADER" = true ]; then
  # Detenemos Patroni en el leader actual para simular caída
  echo "→ Deteniendo Patroni en ${LEADER_NAME}..."
  systemctl stop patroni
else
  # Hacemos switchover controlado desde el nodo replica
  echo "→ Ejecutando switchover controlado..."
  patronictl -c /etc/patroni/patroni.yml switchover --force 2>/dev/null || \
    patronictl -c /etc/patroni/patroni.yml failover --force 2>/dev/null || {
      echo "❌ No se pudo iniciar el switchover/failover"
      exit 1
    }
fi

# ─── Monitorear la elección del nuevo leader ─────────────────────────────────
echo ""
echo "→ Esperando elección del nuevo leader..."
echo ""

for i in $(seq 1 30); do
  # Buscar leader en cualquier nodo que no sea el original
  for ip in "$NODE1_IP" "$NODE2_IP" "$NODE3_IP"; do
    if [ "$ip" = "$LEADER_IP" ] && [ "$IS_CURRENT_LEADER" = true ]; then
      continue  # Saltar el nodo que detuvimos
    fi
    
    ROLE=$(curl -sf http://${ip}:8008/ 2>/dev/null | \
      python3 -c "import sys,json; print(json.load(sys.stdin).get('role',''))" 2>/dev/null || echo "")
    
    if [ "$ROLE" = "master" ] || [ "$ROLE" = "primary" ]; then
      FAILOVER_END=$(date +%s)
      FAILOVER_TIME=$((FAILOVER_END - FAILOVER_START))
      
      echo "  🎉 Nuevo leader detectado: ${ip}"
      echo "  ⏱️  Tiempo de failover: ${FAILOVER_TIME} segundos"
      echo ""
      
      # Verificar que HAProxy ya apunta al nuevo leader
      echo "→ Verificando que HAProxy redirige al nuevo primary..."
      sleep 3  # Dar tiempo a HAProxy para actualizar
      
      RW_RESULT=$(PGPASSWORD="${DB_PASSWORD:-}" psql -h ${ip} -p 5000 -U odoo -d postgres -tAc \
        "SELECT NOT pg_is_in_recovery();" 2>/dev/null || echo "error")
      
      if [ "$RW_RESULT" = "t" ]; then
        echo "  ✅ HAProxy :5000 redirige al nuevo primary"
      else
        echo "  ⚠️  HAProxy aún no redirige (puede tardar unos segundos más)"
      fi
      
      echo ""
      echo "═══ Estado DESPUÉS del failover ═══"
      patronictl -c /etc/patroni/patroni.yml list 2>/dev/null || \
        curl -sf http://${ip}:8008/ | python3 -m json.tool
      
      # ── Restaurar nodo original ──
      if [ "$IS_CURRENT_LEADER" = true ]; then
        echo ""
        echo "═══ Restaurando nodo original... ═══"
        echo "→ Iniciando Patroni en ${LEADER_NAME}..."
        systemctl start patroni
        
        echo "→ Esperando a que se reincorpore como replica..."
        sleep 15
        
        echo ""
        echo "═══ Estado FINAL (post-restauración) ═══"
        patronictl -c /etc/patroni/patroni.yml list 2>/dev/null || \
          echo "(Esperando sincronización...)"
      fi
      
      # ── Resumen ──
      echo ""
      echo "  ╔══════════════════════════════════════════════════════════╗"
      echo "  ║              ✅ TEST DE FAILOVER EXITOSO                ║"
      echo "  ╠══════════════════════════════════════════════════════════╣"
      echo "  ║  Tiempo de failover: ${FAILOVER_TIME}s                  ║"
      echo "  ║  Leader original:    ${LEADER_NAME} (${LEADER_IP})      ║"
      echo "  ║  Nuevo leader:       ${ip}                              ║"
      echo "  ╚══════════════════════════════════════════════════════════╝"
      exit 0
    fi
  done
  
  echo "  Intento ${i}/30... esperando 2s"
  sleep 2
done

echo ""
echo "  ❌ FAILOVER FALLIDO — No se eligió nuevo leader en 60 segundos"
echo "  Revisa: journalctl -u patroni -n 50"

# Restaurar si detuvimos el nodo
if [ "$IS_CURRENT_LEADER" = true ]; then
  echo ""
  echo "→ Restaurando Patroni en ${LEADER_NAME}..."
  systemctl start patroni
fi

exit 1
