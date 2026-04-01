#!/bin/bash
# =============================================================================
# 05b-setup-stunnel-s3proxy.sh — TLS proxy para RadosGW HTTP → HTTPS local
#
# pgBackRest requiere HTTPS para S3. RadosGW solo tiene HTTP.
# stunnel convierte la conexión: pgBackRest → HTTPS:localhost:18480 → stunnel → HTTP:10.40.1.240:7480
#
# Variables requeridas:
#   RADOSGW_ENDPOINT  — http://<host>:<port> del RadosGW real
# =============================================================================
set -euo pipefail

echo "══════════════════════════════════════════════════"
echo "  05b-stunnel-s3proxy — TLS proxy para RadosGW"
echo "══════════════════════════════════════════════════"

: "${RADOSGW_ENDPOINT:?ERROR: RADOSGW_ENDPOINT no definido}"

# Extraer host:port del endpoint HTTP
RGW_HOST_PORT="${RADOSGW_ENDPOINT#http://}"
RGW_HOST_PORT="${RGW_HOST_PORT#https://}"
RGW_HOST="${RGW_HOST_PORT%%:*}"
RGW_PORT="${RGW_HOST_PORT##*:}"

STUNNEL_LISTEN_PORT=18480

echo "→ RadosGW real: http://${RGW_HOST}:${RGW_PORT}"
echo "→ Proxy TLS local: https://127.0.0.1:${STUNNEL_LISTEN_PORT}"

# ─── Instalar stunnel ────────────────────────────────────────────────────────
echo "→ Instalando stunnel4..."
apt-get install -y -qq stunnel4

# ─── Generar certificado self-signed para el proxy ───────────────────────────
echo "→ Generando certificado TLS para stunnel..."
mkdir -p /etc/stunnel

if [ ! -f /etc/stunnel/s3proxy.pem ]; then
  openssl req -x509 -newkey rsa:2048 \
    -keyout /etc/stunnel/s3proxy.key \
    -out /etc/stunnel/s3proxy.crt \
    -days 3650 -nodes \
    -subj "/CN=s3proxy-local" \
    -quiet
  cat /etc/stunnel/s3proxy.crt /etc/stunnel/s3proxy.key > /etc/stunnel/s3proxy.pem
  chmod 600 /etc/stunnel/s3proxy.pem /etc/stunnel/s3proxy.key
  echo "  Certificado generado"
else
  echo "  Certificado ya existe"
fi

# ─── Configurar stunnel ───────────────────────────────────────────────────────
echo "→ Configurando stunnel..."

cat > /etc/stunnel/s3proxy.conf <<EOF
; stunnel — S3/RadosGW TLS proxy
; Acepta HTTPS en localhost:${STUNNEL_LISTEN_PORT} y reenvía a HTTP RadosGW

pid = /var/run/stunnel4/s3proxy.pid
setuid = nobody
setgid = nogroup

; Habilitar FIPS: no
fips = no

[s3proxy]
; Modo: TLS "server" hacia el cliente (pgBackRest), sin TLS hacia el backend
; client = no → stunnel actúa como servidor TLS
accept  = 127.0.0.1:${STUNNEL_LISTEN_PORT}
connect = ${RGW_HOST}:${RGW_PORT}
cert    = /etc/stunnel/s3proxy.pem
EOF

# ─── Configurar servicio systemd ─────────────────────────────────────────────
echo "→ Configurando servicio stunnel..."

# Habilitar stunnel (Ubuntu requiere este archivo)
echo "ENABLED=1" > /etc/default/stunnel4

cat > /etc/systemd/system/stunnel-s3proxy.service <<'UNIT'
[Unit]
Description=stunnel S3/RadosGW TLS proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
PIDFile=/var/run/stunnel4/s3proxy.pid
ExecStartPre=/bin/mkdir -p /var/run/stunnel4
ExecStartPre=/bin/chown nobody:nogroup /var/run/stunnel4
ExecStart=/usr/bin/stunnel /etc/stunnel/s3proxy.conf
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable stunnel-s3proxy
systemctl restart stunnel-s3proxy
sleep 2

if systemctl is-active --quiet stunnel-s3proxy; then
  echo "  ✅ stunnel activo en 127.0.0.1:${STUNNEL_LISTEN_PORT}"
else
  echo "  ❌ stunnel no inició. Ver: journalctl -u stunnel-s3proxy -n 20"
  journalctl -u stunnel-s3proxy -n 20 --no-pager
  exit 1
fi

# ─── Verificar conectividad ──────────────────────────────────────────────────
echo "→ Verificando proxy..."
sleep 1
if curl -sk "https://127.0.0.1:${STUNNEL_LISTEN_PORT}/" -o /dev/null; then
  echo "  ✅ Proxy S3 respondiendo correctamente"
else
  echo "  ⚠️  Proxy no responde (puede ser normal si RadosGW requiere auth)"
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ stunnel configurado como proxy TLS para S3"
echo ""
echo "  pgBackRest debe usar endpoint: https://127.0.0.1:${STUNNEL_LISTEN_PORT}"
echo "  Backend real:                  http://${RGW_HOST}:${RGW_PORT}"
echo "══════════════════════════════════════════════════"
