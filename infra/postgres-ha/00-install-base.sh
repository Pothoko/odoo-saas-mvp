#!/bin/bash
# =============================================================================
# 00-install-base.sh — Instala todos los paquetes necesarios en una VM
#
# Se ejecuta en cada VM vía SSH desde deploy-all.sh:
#   ssh -i ~/.ssh/id_rsa ubuntu@10.40.2.182 "sudo bash -s" < 00-install-base.sh
#
# Target OS: Ubuntu 24.04
# Instala: PostgreSQL 16, Patroni, etcd, PgBouncer, HAProxy, pgBackRest,
#          node_exporter, postgres_exporter
# =============================================================================
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "══════════════════════════════════════════════════"
echo "  00-install-base.sh — Instalando paquetes base"
echo "══════════════════════════════════════════════════"

# ─── 1. Actualizar sistema ───────────────────────────────────────────────────
echo "→ Actualizando sistema..."
apt-get update -qq
apt-get upgrade -y -qq

# ─── 2. Paquetes básicos ────────────────────────────────────────────────────
echo "→ Instalando dependencias básicas..."
apt-get install -y -qq \
  curl \
  wget \
  gnupg2 \
  lsb-release \
  ca-certificates \
  apt-transport-https \
  software-properties-common \
  python3 \
  python3-pip \
  python3-venv \
  jq \
  net-tools \
  iputils-ping \
  dnsutils \
  sysstat \
  htop \
  vim \
  unzip

# ─── 3. PostgreSQL 16 (PGDG) ────────────────────────────────────────────────
echo "→ Instalando PostgreSQL 16..."
if ! dpkg -l | grep -q postgresql-16; then
  # Agregar repositorio oficial PGDG
  # --batch --yes: necesario cuando se ejecuta sin TTY (via SSH pipe)
  curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | \
    gpg --batch --yes --dearmor -o /usr/share/keyrings/pgdg-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/pgdg-archive-keyring.gpg] \
    https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
  apt-get update -qq
  apt-get install -y -qq postgresql-16 postgresql-contrib-16 postgresql-client-16
  
  # Detener y deshabilitar el servicio PostgreSQL por defecto
  # Patroni va a manejar PostgreSQL
  systemctl stop postgresql
  systemctl disable postgresql
  echo "  PostgreSQL 16 instalado y detenido (Patroni lo gestionará)"
else
  echo "  PostgreSQL 16 ya instalado"
fi

# ─── 4. Patroni ─────────────────────────────────────────────────────────────
echo "→ Instalando Patroni..."
if ! command -v patroni &>/dev/null; then
  # Instalar en un virtualenv dedicado para evitar conflictos con system python
  python3 -m venv /opt/patroni/venv
  /opt/patroni/venv/bin/pip install --upgrade pip
  /opt/patroni/venv/bin/pip install patroni[etcd3] psycopg2-binary

  # Crear symlink para acceso global
  ln -sf /opt/patroni/venv/bin/patroni /usr/local/bin/patroni
  ln -sf /opt/patroni/venv/bin/patronictl /usr/local/bin/patronictl

  echo "  Patroni instalado en /opt/patroni/venv"
else
  echo "  Patroni ya instalado"
fi

# ─── 5. etcd ─────────────────────────────────────────────────────────────────
echo "→ Instalando etcd..."
if ! command -v etcd &>/dev/null; then
  ETCD_VER=v3.5.17
  DOWNLOAD_URL=https://github.com/etcd-io/etcd/releases/download

  curl -fsSL "${DOWNLOAD_URL}/${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz" \
    -o /tmp/etcd.tar.gz
  tar xzf /tmp/etcd.tar.gz -C /tmp/
  mv /tmp/etcd-${ETCD_VER}-linux-amd64/etcd /usr/local/bin/
  mv /tmp/etcd-${ETCD_VER}-linux-amd64/etcdctl /usr/local/bin/
  mv /tmp/etcd-${ETCD_VER}-linux-amd64/etcdutl /usr/local/bin/
  rm -rf /tmp/etcd*

  # Crear usuario y directorio de datos para etcd
  useradd --system --no-create-home --shell /bin/false etcd 2>/dev/null || true
  mkdir -p /var/lib/etcd
  chown etcd:etcd /var/lib/etcd
  chmod 700 /var/lib/etcd

  echo "  etcd ${ETCD_VER} instalado"
else
  echo "  etcd ya instalado: $(etcd --version | head -1)"
fi

# ─── 6. PgBouncer ───────────────────────────────────────────────────────────
echo "→ Instalando PgBouncer..."
if ! command -v pgbouncer &>/dev/null; then
  apt-get install -y -qq pgbouncer
  systemctl stop pgbouncer
  systemctl disable pgbouncer
  echo "  PgBouncer instalado y detenido (se configurará después)"
else
  echo "  PgBouncer ya instalado"
fi

# ─── 7. HAProxy ─────────────────────────────────────────────────────────────
echo "→ Instalando HAProxy..."
if ! command -v haproxy &>/dev/null; then
  # Ubuntu 24.04 (Noble) ya incluye HAProxy 2.8 en sus repos por defecto.
  # El PPA vbernat/haproxy-2.8 NO soporta Noble — usar repos base directamente.
  apt-get install -y -qq haproxy
  systemctl stop haproxy
  systemctl disable haproxy
  echo "  HAProxy instalado y detenido (se configurará después)"
else
  echo "  HAProxy ya instalado: $(haproxy -v | head -1)"
fi

# ─── 7b. awscli (opcional, para verificar buckets S3/RadosGW) ───────────────
echo "→ Instalando awscli..."
if ! command -v aws &>/dev/null; then
  # awscli no está en repos de Ubuntu 24.04 — instalar via pip3
  # || true: el deploy continúa aunque falle (awscli es solo para diagnóstico)
  pip3 install --quiet --break-system-packages awscli 2>/dev/null && \
    echo "  awscli instalado via pip3" || \
    echo "  awscli no disponible (opcional — usar curl para verificar RadosGW)"
else
  echo "  awscli ya instalado"
fi

# ─── 8. pgBackRest ──────────────────────────────────────────────────────────
echo "→ Instalando pgBackRest..."
if ! command -v pgbackrest &>/dev/null; then
  apt-get install -y -qq pgbackrest
  
  # Crear directorios de log y config
  mkdir -p /var/log/pgbackrest
  mkdir -p /etc/pgbackrest
  mkdir -p /var/lib/pgbackrest
  chown postgres:postgres /var/log/pgbackrest /var/lib/pgbackrest
  
  echo "  pgBackRest instalado"
else
  echo "  pgBackRest ya instalado: $(pgbackrest version)"
fi

# ─── 9. node_exporter (Prometheus) ──────────────────────────────────────────
echo "→ Instalando node_exporter..."
if ! command -v node_exporter &>/dev/null; then
  NODE_EXPORTER_VER=1.8.2
  curl -fsSL "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VER}/node_exporter-${NODE_EXPORTER_VER}.linux-amd64.tar.gz" \
    -o /tmp/node_exporter.tar.gz
  tar xzf /tmp/node_exporter.tar.gz -C /tmp/
  mv /tmp/node_exporter-${NODE_EXPORTER_VER}.linux-amd64/node_exporter /usr/local/bin/
  rm -rf /tmp/node_exporter*

  useradd --system --no-create-home --shell /bin/false node_exporter 2>/dev/null || true

  cat > /etc/systemd/system/node_exporter.service <<'UNIT'
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable --now node_exporter
  echo "  node_exporter ${NODE_EXPORTER_VER} instalado y activo en :9100"
else
  echo "  node_exporter ya instalado"
fi

# ─── 10. postgres_exporter (Prometheus) ─────────────────────────────────────
echo "→ Instalando postgres_exporter..."
if ! command -v postgres_exporter &>/dev/null; then
  PG_EXPORTER_VER=0.15.0
  curl -fsSL "https://github.com/prometheus-community/postgres_exporter/releases/download/v${PG_EXPORTER_VER}/postgres_exporter-${PG_EXPORTER_VER}.linux-amd64.tar.gz" \
    -o /tmp/pg_exporter.tar.gz
  tar xzf /tmp/pg_exporter.tar.gz -C /tmp/
  mv /tmp/postgres_exporter-${PG_EXPORTER_VER}.linux-amd64/postgres_exporter /usr/local/bin/
  rm -rf /tmp/pg_exporter*

  useradd --system --no-create-home --shell /bin/false postgres_exporter 2>/dev/null || true

  echo "  postgres_exporter ${PG_EXPORTER_VER} instalado (se configurará después)"
else
  echo "  postgres_exporter ya instalado"
fi

# ─── 11. Preparar directorios de Patroni ────────────────────────────────────
echo "→ Preparando directorios para Patroni..."
mkdir -p /etc/patroni
mkdir -p /etc/patroni/callbacks
mkdir -p /var/lib/postgresql/16/patroni
chown -R postgres:postgres /var/lib/postgresql/16/patroni
chmod 700 /var/lib/postgresql/16/patroni

# ─── 12. Ajustes del sistema ────────────────────────────────────────────────
echo "→ Aplicando ajustes del sistema..."

# Aumentar límites de archivos abiertos
cat > /etc/security/limits.d/postgres.conf <<'LIMITS'
postgres    soft    nofile    65536
postgres    hard    nofile    65536
postgres    soft    nproc     65536
postgres    hard    nproc     65536
LIMITS

# Ajustes de kernel para PostgreSQL
cat > /etc/sysctl.d/99-postgresql.conf <<'SYSCTL'
# PostgreSQL performance tuning
vm.swappiness = 1
vm.overcommit_memory = 2
vm.overcommit_ratio = 90
vm.dirty_ratio = 10
vm.dirty_background_ratio = 3
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_tw_reuse = 1
SYSCTL

sysctl --system -q

echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ 00-install-base.sh completado"
echo "══════════════════════════════════════════════════"
echo ""
echo "  Componentes instalados:"
echo "    • PostgreSQL $(pg_config --version 2>/dev/null || echo '16')"
echo "    • Patroni $(patroni --version 2>/dev/null || echo 'OK')"
echo "    • etcd $(etcd --version 2>/dev/null | head -1 || echo 'OK')"
echo "    • PgBouncer $(pgbouncer --version 2>/dev/null | head -1 || echo 'OK')"
echo "    • HAProxy $(haproxy -v 2>/dev/null | head -1 || echo 'OK')"
echo "    • pgBackRest $(pgbackrest version 2>/dev/null || echo 'OK')"
echo "    • node_exporter :9100"
echo "    • postgres_exporter (pendiente de configurar)"
echo ""
