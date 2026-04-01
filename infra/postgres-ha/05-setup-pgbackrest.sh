#!/bin/bash
# =============================================================================
# 05-setup-pgbackrest.sh — Configura pgBackRest para backups a RadosGW (S3)
#
# pgBackRest se integra con Patroni vía archive_command para WAL archiving
# continuo, y ejecuta backups full/diff via cron.
#
# Variables requeridas:
#   RADOSGW_ENDPOINT      — http://<rgw_host>:7480
#   S3_ACCESS_KEY         — Access key del usuario pgbackrest en RadosGW
#   S3_SECRET_KEY         — Secret key del usuario pgbackrest en RadosGW
#   S3_BUCKET             — pg-backups (default)
#   BACKUP_ENCRYPTION_KEY — Clave para cifrar backups
#   PG_SUPERUSER_PASSWORD — Para conectar a PostgreSQL
# =============================================================================
set -euo pipefail

echo "══════════════════════════════════════════════════"
echo "  05-setup-pgbackrest.sh — Configurando pgBackRest"
echo "══════════════════════════════════════════════════"

: "${RADOSGW_ENDPOINT:?ERROR: RADOSGW_ENDPOINT no definido}"
: "${S3_ACCESS_KEY:?ERROR: S3_ACCESS_KEY no definido}"
: "${S3_SECRET_KEY:?ERROR: S3_SECRET_KEY no definido}"
: "${BACKUP_ENCRYPTION_KEY:?ERROR: BACKUP_ENCRYPTION_KEY no definido}"
: "${PG_SUPERUSER_PASSWORD:?ERROR: PG_SUPERUSER_PASSWORD no definido}"

S3_BUCKET="${S3_BUCKET:-pg-backups}"

# pgBackRest siempre usa HTTPS para S3.
# RadosGW solo tiene HTTP, así que usamos el stunnel proxy local (05b-setup-stunnel-s3proxy.sh)
# que escucha HTTPS en 127.0.0.1:18480 y reenvía a HTTP RadosGW.
STUNNEL_ENDPOINT="127.0.0.1:18480"

echo "→ Usando proxy TLS local stunnel → ${RADOSGW_ENDPOINT}"

# ─── Generar configuración de pgBackRest ────────────────────────────────────
echo "→ Generando /etc/pgbackrest/pgbackrest.conf..."

mkdir -p /etc/pgbackrest

cat > /etc/pgbackrest/pgbackrest.conf <<EOF
# ─────────────────────────────────────────────────────────────────────────────
# pgBackRest Configuration — Odoo SaaS HA Cluster
# Backup repository: RadosGW (S3-compatible) on Ceph
# ─────────────────────────────────────────────────────────────────────────────

[global]
# ─── S3 Repository (RadosGW) ────────────────────────────────────────────────
repo1-type=s3
repo1-s3-endpoint=${STUNNEL_ENDPOINT}
repo1-s3-bucket=${S3_BUCKET}
repo1-s3-region=default
repo1-s3-key=${S3_ACCESS_KEY}
repo1-s3-key-secret=${S3_SECRET_KEY}
repo1-s3-uri-style=path
# stunnel proxy local — self-signed cert, no verificar TLS
repo1-s3-verify-tls=n
repo1-path=/odoo-saas-ha

# ─── Retención ──────────────────────────────────────────────────────────────
repo1-retention-full=4
repo1-retention-diff=14
repo1-retention-archive=4
repo1-retention-archive-type=full

# ─── Cifrado ────────────────────────────────────────────────────────────────
repo1-cipher-type=aes-256-cbc
repo1-cipher-pass=${BACKUP_ENCRYPTION_KEY}

# ─── Compresión ─────────────────────────────────────────────────────────────
compress-type=zst
compress-level=3

# ─── Performance ────────────────────────────────────────────────────────────
process-max=2

# ─── Logging ────────────────────────────────────────────────────────────────
log-level-console=info
log-level-file=detail
log-path=/var/log/pgbackrest

# ─── Stanza ─────────────────────────────────────────────────────────────────
[odoo-saas]
pg1-path=/var/lib/postgresql/16/patroni
pg1-port=5432
pg1-user=postgres
pg1-socket-path=/var/run/postgresql
EOF

# Permisos: solo postgres puede leer (contiene claves S3)
chown postgres:postgres /etc/pgbackrest/pgbackrest.conf
chmod 600 /etc/pgbackrest/pgbackrest.conf

# Asegurar directorios de log
mkdir -p /var/log/pgbackrest
chown postgres:postgres /var/log/pgbackrest

# ─── Crear stanza (solo en el primary) ───────────────────────────────────────
echo "→ Verificando si este nodo es primary..."

IS_PRIMARY=$(su - postgres -c "psql -h 127.0.0.1 -p 5432 -tAc \
  'SELECT NOT pg_is_in_recovery();'" 2>/dev/null || echo "f")

if [ "$IS_PRIMARY" = "t" ]; then
  echo "→ Este nodo es primary. Creando stanza..."
  
  # Crear stanza
  su - postgres -c "pgbackrest --stanza=odoo-saas stanza-create" || {
    echo "  ⚠️  Error al crear stanza. ¿RadosGW accesible?"
    echo "  Verificar: curl ${RADOSGW_ENDPOINT}"
    echo "  Puedes crear la stanza manualmente más tarde:"
    echo "  sudo -u postgres pgbackrest --stanza=odoo-saas stanza-create"
  }

  # Verificar stanza
  echo "→ Verificando stanza..."
  su - postgres -c "pgbackrest --stanza=odoo-saas check" || {
    echo "  ⚠️  Check de stanza falló. Esto puede ser normal si"
    echo "  archive_command aún no ha enviado el primer WAL."
    echo "  Intentar después: sudo -u postgres pgbackrest --stanza=odoo-saas check"
  }

  # Ejecutar primer backup full
  echo "→ Ejecutando primer backup full (esto puede tomar varios minutos)..."
  su - postgres -c "pgbackrest --stanza=odoo-saas --type=full backup" && {
    echo "  ✅ Primer backup full completado!"
  } || {
    echo "  ⚠️  Backup full falló. Ejecutar manualmente:"
    echo "  sudo -u postgres pgbackrest --stanza=odoo-saas --type=full backup"
  }
else
  echo "  Este nodo es replica. La stanza se creará desde el primary."
  echo "  pgBackRest puede ejecutar archive-push desde cualquier nodo."
fi

# ─── Configurar cron para backups automáticos ────────────────────────────────
echo "→ Configurando cron de backups..."

# Solo el primary debe ejecutar backups.
# Usamos un wrapper que verifica el rol antes de ejecutar.
cat > /usr/local/bin/pgbackrest-backup.sh <<'BACKUP_SCRIPT'
#!/bin/bash
# pgBackRest backup wrapper — solo ejecuta si el nodo es primary
set -euo pipefail

# Verificar si somos primary
IS_PRIMARY=$(psql -h 127.0.0.1 -p 5432 -U postgres -tAc \
  "SELECT NOT pg_is_in_recovery();" 2>/dev/null || echo "f")

if [ "$IS_PRIMARY" != "t" ]; then
  echo "$(date): Este nodo no es primary, saltando backup."
  exit 0
fi

BACKUP_TYPE="${1:-diff}"
echo "$(date): Iniciando backup ${BACKUP_TYPE}..."

pgbackrest --stanza=odoo-saas --type="${BACKUP_TYPE}" backup

echo "$(date): Backup ${BACKUP_TYPE} completado."

# Mostrar info
pgbackrest --stanza=odoo-saas info
BACKUP_SCRIPT

chmod +x /usr/local/bin/pgbackrest-backup.sh
chown postgres:postgres /usr/local/bin/pgbackrest-backup.sh

# Agregar al crontab de postgres
CRONTAB_CONTENT=$(su - postgres -c "crontab -l" 2>/dev/null || echo "")

# Evitar duplicados
if ! echo "$CRONTAB_CONTENT" | grep -q "pgbackrest-backup.sh"; then
  (echo "$CRONTAB_CONTENT"
   echo ""
   echo "# ─── pgBackRest Backups ───"
   echo "# Full backup: domingos 2:00 AM (America/La_Paz)"
   echo "0 2 * * 0 /usr/local/bin/pgbackrest-backup.sh full >> /var/log/pgbackrest/cron.log 2>&1"
   echo "# Differential backup: lunes a sábado 2:00 AM"
   echo "0 2 * * 1-6 /usr/local/bin/pgbackrest-backup.sh diff >> /var/log/pgbackrest/cron.log 2>&1"
  ) | su - postgres -c "crontab -"
  echo "  Cron configurado para backups automáticos"
else
  echo "  Cron de backups ya existente"
fi

# ─── Verificar estado ───────────────────────────────────────────────────────
echo ""
echo "→ Estado de pgBackRest:"
su - postgres -c "pgbackrest --stanza=odoo-saas info" 2>/dev/null || \
  echo "  (Stanza pendiente de creación o verificación)"

echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ pgBackRest configurado"
echo ""
echo "  Repository: ${RADOSGW_ENDPOINT}/${S3_BUCKET}/odoo-saas-ha"
echo "  Schedule:"
echo "    Full:  Domingos 2:00 AM"
echo "    Diff:  Lun-Sáb 2:00 AM"
echo "    WAL:   Continuo (archive_command)"
echo ""
echo "  Comandos útiles:"
echo "    sudo -u postgres pgbackrest --stanza=odoo-saas info"
echo "    sudo -u postgres pgbackrest --stanza=odoo-saas check"
echo "    sudo -u postgres pgbackrest --stanza=odoo-saas --type=full backup"
echo "══════════════════════════════════════════════════"
