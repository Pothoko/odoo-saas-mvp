/**
 * Odoo SaaS Portal — Frontend Application
 * Vanilla JS SPA, no dependencies, served by FastAPI StaticFiles.
 * All API calls go through the `Api` module which handles auth and errors.
 */

// =============================================================================
// CONFIG — reads from localStorage, settable via Settings page
// =============================================================================
const Config = (() => {
  const DEFAULTS = {
    apiKey:  'dev-api-key-local',
    baseUrl: '',  // '' = same origin
  };

  function get(key) {
    const stored = localStorage.getItem(`saas_portal_${key}`);
    return stored !== null ? stored : DEFAULTS[key];
  }

  function set(key, value) {
    localStorage.setItem(`saas_portal_${key}`, value);
  }

  function getAll() {
    return { apiKey: get('apiKey'), baseUrl: get('baseUrl') };
  }

  return { get, set, getAll };
})();

// =============================================================================
// API — fetch wrapper with auth, error handling, structured responses
// =============================================================================
const Api = (() => {
  function headers() {
    return {
      'Content-Type': 'application/json',
      'X-API-Key': Config.get('apiKey'),
    };
  }

  function url(path) {
    const base = Config.get('baseUrl').replace(/\/$/, '');
    return `${base}${path}`;
  }

  async function request(method, path, body = undefined) {
    const opts = { method, headers: headers() };
    if (body !== undefined) opts.body = JSON.stringify(body);

    let resp;
    try {
      resp = await fetch(url(path), opts);
    } catch (err) {
      // Network error
      throw new ApiError('NetworkError', `No se pudo conectar al portal: ${err.message}`, 0);
    }

    let data;
    try {
      data = await resp.json();
    } catch {
      data = { detail: resp.statusText };
    }

    if (!resp.ok) {
      const detail = data.detail || data.error || JSON.stringify(data);
      throw new ApiError(`HTTP ${resp.status}`, detail, resp.status);
    }

    return data;
  }

  function get(path)              { return request('GET', path); }
  function post(path, body)       { return request('POST', path, body); }
  function del(path)              { return request('DELETE', path); }
  function put(path, body)        { return request('PUT', path, body); }
  function patch(path, body)      { return request('PATCH', path, body); }

  // Named API calls
  const instances = {
    list:        ()          => get('/api/v1/instances'),
    get:         (id)        => get(`/api/v1/instances/${id}`),
    create:      (body)      => post('/api/v1/instances', body),
    delete:      (id)        => del(`/api/v1/instances/${id}`),
    stop:        (id)        => post(`/api/v1/instances/${id}/stop`),
    start:       (id)        => post(`/api/v1/instances/${id}/start`),
    logs:        (id, lines) => get(`/api/v1/instances/${id}/logs?lines=${lines}`),
    config:      (id)        => get(`/api/v1/instances/${id}/config`),
    saveConfig:  (id, body)  => patch(`/api/v1/instances/${id}/config`, body),
    check:       (id)        => get(`/api/v1/instances/check/${id}`),
    metrics:     (id)        => get(`/api/v1/instances/${id}/metrics`),
  };

  const health = () => get('/healthz');

  return { instances, health };
})();

class ApiError extends Error {
  constructor(type, detail, status) {
    super(detail);
    this.type   = type;
    this.detail = detail;
    this.status = status;
  }
}

// =============================================================================
// STORE — minimal reactive state
// =============================================================================
const Store = (() => {
  let _tenants     = [];
  let _loading     = false;
  let _currentView = 'dashboard';
  let _selectedId  = null;
  let _searchQuery = '';
  let _lastCreated = null;

  const _listeners = new Set();

  function notify() {
    _listeners.forEach(fn => fn());
  }

  return {
    subscribe(fn) { _listeners.add(fn); return () => _listeners.delete(fn); },

    get tenants()     { return _tenants; },
    get loading()     { return _loading; },
    get currentView() { return _currentView; },
    get selectedId()  { return _selectedId; },
    get searchQuery() { return _searchQuery; },
    get lastCreated() { return _lastCreated; },

    setTenants(t)     { _tenants = t; notify(); },
    setLoading(v)     { _loading = v; notify(); },
    setView(v)        { _currentView = v; notify(); },
    setSelectedId(id) { _selectedId = id; notify(); },
    setSearchQuery(q) { _searchQuery = q; notify(); },
    setLastCreated(t) { _lastCreated = t; },

    filteredTenants() {
      const q = _searchQuery.toLowerCase().trim();
      if (!q) return _tenants;
      return _tenants.filter(t =>
        t.tenant_id.includes(q) ||
        t.plan.includes(q) ||
        t.status.includes(q)
      );
    },

    getTenant(id) { return _tenants.find(t => t.tenant_id === id); },
  };
})();

// =============================================================================
// TOAST — notification system
// =============================================================================
const Toast = (() => {
  const ICONS = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

  function show(type, title, body = '', duration = 4500) {
    const container = document.getElementById('toast-container');
    const id = `toast-${Date.now()}`;

    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.id = id;
    el.innerHTML = `
      <div class="toast-icon">${ICONS[type] || 'ℹ️'}</div>
      <div>
        <div class="toast-title">${escapeHtml(title)}</div>
        ${body ? `<div class="toast-body">${escapeHtml(body)}</div>` : ''}
      </div>
      <button class="toast-close" onclick="Toast.dismiss('${id}')">✕</button>
    `;
    container.appendChild(el);

    if (duration > 0) {
      setTimeout(() => Toast.dismiss(id), duration);
    }
    return id;
  }

  function dismiss(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add('toast-exit');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }

  return {
    dismiss,
    success: (title, body, dur) => show('success', title, body, dur),
    error:   (title, body, dur) => show('error',   title, body, dur),
    warning: (title, body, dur) => show('warning', title, body, dur),
    info:    (title, body, dur) => show('info',    title, body, dur),
  };
})();

// =============================================================================
// UTILS
// =============================================================================
function escapeHtml(str) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(str ?? '')));
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return 'N/D';
  try {
    return new Date(iso).toLocaleDateString('es-VE', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function relativeTime(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60)   return 'hace un momento';
  const m = Math.floor(s / 60);
  if (m < 60)   return `hace ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24)   return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return `hace ${d} día${d !== 1 ? 's' : ''}`;
}

function statusBadge(status) {
  const map = {
    ready:        ['badge-ready',        '🟢', 'Activo'],
    provisioning: ['badge-provisioning', '🟡', 'Iniciando'],
    terminating:  ['badge-terminating',  '🔴', 'Eliminando'],
    suspended:    ['badge-suspended',    '⚫', 'Suspendido'],
  };
  const [cls, , label] = map[status] || ['badge-suspended', '⚫', status];
  return `<span class="badge ${cls}"><span class="badge-dot"></span>${escapeHtml(label)}</span>`;
}

function planBadge(plan) {
  return `<span class="badge badge-plan">${escapeHtml(plan)}</span>`;
}

function tenantInitials(id) {
  return id.substring(0, 2).toUpperCase();
}

function avatarGradient(id) {
  // Deterministic color per tenant
  let hash = 0;
  for (const c of id) hash = (hash * 31 + c.charCodeAt(0)) & 0xffffffff;
  const hue = Math.abs(hash % 360);
  return `hsl(${hue},60%,55%)`;
}

function colorizeLog(text) {
  return text
    .replace(/\b(ERROR|CRITICAL|FATAL)\b/gi, '<span class="log-error">$1</span>')
    .replace(/\b(WARNING|WARN)\b/gi, '<span class="log-warning">$1</span>')
    .replace(/\b(INFO)\b/gi, '<span class="log-info">$1</span>');
}

// =============================================================================
// VIEWS — render functions
// =============================================================================
const Views = {

  // ── Dashboard ───────────────────────────────────────────────────────────────
  dashboard() {
    const tenants  = Store.tenants;
    const total    = tenants.length;
    const ready    = tenants.filter(t => t.status === 'ready').length;
    const starting = tenants.filter(t => t.status === 'provisioning').length;
    const users    = tenants.reduce((acc, t) => acc + (t.user_count || 0), 0);

    const recentTenants = [...tenants]
      .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
      .slice(0, 5);

    return `
      <div class="page-enter">
        <div class="page-header">
          <div class="page-header-text">
            <h1>Dashboard</h1>
            <p>Resumen general de tus instancias Odoo</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-primary" onclick="App.navigate('create')">
              ✨ Nuevo Tenant
            </button>
          </div>
        </div>

        <!-- Stats -->
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-icon purple">🏢</div>
            <div>
              <div class="stat-value">${total}</div>
              <div class="stat-label">Tenants totales</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon green">✅</div>
            <div>
              <div class="stat-value" style="color:var(--color-success)">${ready}</div>
              <div class="stat-label">Activos</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon yellow">⏳</div>
            <div>
              <div class="stat-value" style="color:var(--color-warning)">${starting}</div>
              <div class="stat-label">Iniciando</div>
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-icon blue">👥</div>
            <div>
              <div class="stat-value">${users}</div>
              <div class="stat-label">Usuarios totales</div>
            </div>
          </div>
        </div>

        <!-- Recent tenants -->
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">Tenants recientes</div>
              <div class="card-subtitle">Últimas instancias creadas</div>
            </div>
            <button class="btn btn-sm btn-secondary" onclick="App.navigate('tenants')">Ver todos →</button>
          </div>
          ${recentTenants.length === 0
            ? `<div class="empty-state">
                <div class="empty-icon">🏗</div>
                <div class="empty-title">Sin tenants aún</div>
                <div class="empty-desc">Crea tu primer tenant con el botón "Nuevo Tenant"</div>
                <button class="btn btn-primary" onclick="App.navigate('create')">✨ Crear el primero</button>
              </div>`
            : `<div class="tenants-table-wrapper" style="border:none;background:transparent">
                <table class="tenants-table">
                  <thead>
                    <tr>
                      <th>Tenant</th>
                      <th>Estado</th>
                      <th>Plan</th>
                      <th>Usuarios</th>
                      <th>Creado</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${recentTenants.map(t => `
                      <tr onclick="App.openTenant('${t.tenant_id}')" style="cursor:pointer">
                        <td>
                          <div class="tenant-name-cell">
                            <div class="tenant-avatar" style="background:linear-gradient(135deg,${avatarGradient(t.tenant_id)},var(--color-accent))">
                              ${tenantInitials(t.tenant_id)}
                            </div>
                            <div>
                              <div class="tenant-id">${escapeHtml(t.tenant_id)}</div>
                              <div class="tenant-url">${escapeHtml(t.url || '')}</div>
                            </div>
                          </div>
                        </td>
                        <td>${statusBadge(t.status)}</td>
                        <td>${planBadge(t.plan || 'starter')}</td>
                        <td>${t.user_count || 0}</td>
                        <td>${relativeTime(t.created_at)}</td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>`
          }
        </div>
      </div>
    `;
  },

  // ── Tenants list ─────────────────────────────────────────────────────────────
  tenants() {
    const tenants = Store.filteredTenants();
    const loading = Store.loading;

    return `
      <div class="page-enter">
        <div class="page-header">
          <div class="page-header-text">
            <h1>Tenants</h1>
            <p>${Store.tenants.length} instancia${Store.tenants.length !== 1 ? 's' : ''} en total</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-primary" onclick="App.navigate('create')">
              ✨ Nuevo Tenant
            </button>
          </div>
        </div>

        ${loading
          ? Views._skeleton()
          : tenants.length === 0
            ? Store.tenants.length === 0
              ? `<div class="empty-state">
                  <div class="empty-icon">🏗</div>
                  <div class="empty-title">Sin instancias</div>
                  <div class="empty-desc">No hay tenants creados todavía. ¡Empieza con el primero!</div>
                  <button class="btn btn-primary" onclick="App.navigate('create')">✨ Crear tenant</button>
                </div>`
              : `<div class="empty-state">
                  <div class="empty-icon">🔍</div>
                  <div class="empty-title">Sin resultados</div>
                  <div class="empty-desc">No hay tenants que coincidan con tu búsqueda</div>
                </div>`
            : `<div class="tenants-table-wrapper">
                <table class="tenants-table">
                  <thead>
                    <tr>
                      <th>Tenant</th>
                      <th>Estado</th>
                      <th>Plan</th>
                      <th>Versión</th>
                      <th>Usuarios</th>
                      <th>Creado</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${tenants.map(t => `
                      <tr>
                        <td>
                          <div class="tenant-name-cell">
                            <div class="tenant-avatar" style="background:linear-gradient(135deg,${avatarGradient(t.tenant_id)},var(--color-accent))">
                              ${tenantInitials(t.tenant_id)}
                            </div>
                            <div>
                              <div class="tenant-id">${escapeHtml(t.tenant_id)}</div>
                              <a href="${escapeHtml(t.url || '#')}" target="_blank" rel="noopener"
                                 class="tenant-url" onclick="event.stopPropagation()">
                                ${escapeHtml(t.url || '')} ↗
                              </a>
                            </div>
                          </div>
                        </td>
                        <td>${statusBadge(t.status)}</td>
                        <td>${planBadge(t.plan || 'starter')}</td>
                        <td><span class="font-mono text-xs">${escapeHtml(t.odoo_version || '18.0')}</span></td>
                        <td>${t.user_count || 0}</td>
                        <td title="${escapeHtml(formatDate(t.created_at))}">${relativeTime(t.created_at)}</td>
                        <td>
                          <div class="actions-cell">
                            <button
                              class="btn btn-sm btn-secondary"
                              onclick="App.openTenant('${t.tenant_id}')"
                              title="Ver detalle"
                            >👁</button>
                            ${t.status === 'ready'
                              ? `<button class="btn btn-sm btn-secondary" onclick="Actions.stop('${t.tenant_id}')" title="Suspender">⏸</button>`
                              : t.status === 'suspended'
                                ? `<button class="btn btn-sm btn-secondary" onclick="Actions.start('${t.tenant_id}')" title="Iniciar">▶</button>`
                                : ''}
                            <button
                              class="btn btn-sm btn-danger"
                              onclick="Modals.openDelete('${t.tenant_id}')"
                              title="Eliminar"
                            >🗑</button>
                          </div>
                        </td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>`
        }
      </div>
    `;
  },

  // ── Tenant Detail ─────────────────────────────────────────────────────────────
  tenantDetail(tenant) {
    if (!tenant) {
      return `<div class="empty-state">
        <div class="empty-icon">🔍</div>
        <div class="empty-title">Tenant no encontrado</div>
        <button class="btn btn-secondary" onclick="App.navigate('tenants')">← Volver</button>
      </div>`;
    }

    const cpuPct = tenant.cpu_millicores != null ? Math.min(100, Math.round(tenant.cpu_millicores / 10)) : null;
    const memPct = tenant.memory_mib != null ? Math.min(100, Math.round(tenant.memory_mib / 20.48)) : null;

    return `
      <div class="page-enter">
        <div class="page-header">
          <div class="flex items-center gap-3">
            <button class="btn btn-sm btn-ghost" onclick="App.navigate('tenants')">← Volver</button>
            <div class="tenant-avatar" style="background:linear-gradient(135deg,${avatarGradient(tenant.tenant_id)},var(--color-accent));width:42px;height:42px;font-size:var(--text-base)">
              ${tenantInitials(tenant.tenant_id)}
            </div>
            <div>
              <h1 style="font-size:var(--text-2xl)">${escapeHtml(tenant.tenant_id)}</h1>
              <a href="${escapeHtml(tenant.url || '#')}" target="_blank" rel="noopener"
                 class="text-xs text-muted" style="text-decoration:underline">
                ${escapeHtml(tenant.url || '')} ↗
              </a>
            </div>
          </div>
          <div class="page-actions">
            ${tenant.status === 'ready'
              ? `<button class="btn btn-secondary" onclick="Actions.stop('${tenant.tenant_id}')">⏸ Suspender</button>`
              : `<button class="btn btn-secondary" onclick="Actions.start('${tenant.tenant_id}')">▶ Iniciar</button>`
            }
            <button class="btn btn-secondary" onclick="Actions.openLogs('${tenant.tenant_id}')">📋 Logs</button>
            <button class="btn btn-secondary" onclick="Actions.openConfig('${tenant.tenant_id}')">⚙ Config</button>
            <button class="btn btn-danger" onclick="Modals.openDelete('${tenant.tenant_id}')">🗑 Eliminar</button>
          </div>
        </div>

        <div class="detail-grid">
          <!-- Status card -->
          <div class="card">
            <div class="card-header">
              <div class="card-title">Estado</div>
              <button class="btn btn-sm btn-ghost" onclick="App.refreshDetail('${tenant.tenant_id}')">↻</button>
            </div>
            <div class="flex flex-col gap-4">
              <div class="flex items-center gap-3">
                ${statusBadge(tenant.status)}
                ${planBadge(tenant.plan || 'starter')}
                <span class="badge" style="background:var(--color-accent-bg);color:var(--color-accent);border:1px solid hsla(199,90%,60%,.2)">
                  Odoo ${escapeHtml(tenant.odoo_version || '18.0')}
                </span>
              </div>
              <div class="detail-meta-grid">
                <div class="meta-item">
                  <label>Namespace</label>
                  <span class="font-mono">${escapeHtml(tenant.namespace)}</span>
                </div>
                <div class="meta-item">
                  <label>Usuarios activos</label>
                  <span>${tenant.user_count || 0}</span>
                </div>
                <div class="meta-item">
                  <label>Creado</label>
                  <span>${formatDate(tenant.created_at)}</span>
                </div>
                <div class="meta-item">
                  <label>Actualizado</label>
                  <span>${new Date().toLocaleTimeString('es-VE')}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Metrics card -->
          <div class="card">
            <div class="card-header">
              <div class="card-title">Recursos</div>
              ${tenant.cpu_millicores == null
                ? `<span class="text-xs text-muted">metrics-server no disponible</span>`
                : ''}
            </div>
            ${tenant.cpu_millicores != null
              ? `<div class="flex flex-col gap-4">
                  <div class="metric-wrap">
                    <div class="metric-header">
                      <span class="metric-label">CPU</span>
                      <span class="metric-value">${tenant.cpu_millicores}m</span>
                    </div>
                    <div class="progress-bar-wrap">
                      <div class="progress-bar" style="width:${cpuPct}%"></div>
                    </div>
                  </div>
                  <div class="metric-wrap">
                    <div class="metric-header">
                      <span class="metric-label">Memoria</span>
                      <span class="metric-value">${tenant.memory_mib} MiB</span>
                    </div>
                    <div class="progress-bar-wrap">
                      <div class="progress-bar" style="width:${memPct}%;background:linear-gradient(90deg,var(--color-accent),var(--color-primary))"></div>
                    </div>
                  </div>
                </div>`
              : `<div class="empty-state" style="padding:var(--sp-6)">
                  <div class="empty-icon" style="font-size:32px">📊</div>
                  <div class="empty-desc">Instala metrics-server para ver CPU y memoria en tiempo real</div>
                </div>`
            }
          </div>
        </div>

        <!-- Quick actions horizontal -->
        <div class="flex gap-3 mt-4" style="flex-wrap:wrap">
          <button class="btn btn-secondary" onclick="Actions.openLogs('${tenant.tenant_id}')">
            📋 Ver Logs
          </button>
          <button class="btn btn-secondary" onclick="Actions.openConfig('${tenant.tenant_id}')">
            ⚙ Editar Configuración
          </button>
          <a href="${escapeHtml(tenant.url || '#')}" target="_blank" rel="noopener" class="btn btn-secondary">
            🌐 Abrir Odoo ↗
          </a>
        </div>
      </div>
    `;
  },

  // ── Create (inline form view, modal is separate) ─────────────────────────────
  create() {
    // Just open the modal, show a placeholder view
    Modals.openCreate();
    return `
      <div class="page-enter">
        <div class="page-header">
          <div class="page-header-text">
            <h1>Nuevo Tenant</h1>
            <p>Aprovisionar una nueva instancia de Odoo</p>
          </div>
        </div>
        <div class="empty-state">
          <div class="empty-icon">✨</div>
          <div class="empty-title">Formulario de creación</div>
          <div class="empty-desc">Completa el formulario que se ha abierto para crear tu tenant</div>
          <button class="btn btn-primary" onclick="Modals.openCreate()">Abrir formulario</button>
        </div>
      </div>
    `;
  },

  // ── Settings ──────────────────────────────────────────────────────────────────
  settings() {
    const { apiKey, baseUrl } = Config.getAll();
    return `
      <div class="page-enter">
        <div class="page-header">
          <div class="page-header-text">
            <h1>Configuración</h1>
            <p>Ajustes del portal de administración</p>
          </div>
        </div>

        <div class="settings-section">
          <div class="settings-section-header">🔑 Autenticación</div>

          <div class="settings-row">
            <div class="settings-row-info">
              <label>API Key</label>
              <p>Clave de acceso al portal FastAPI (header X-API-Key)</p>
            </div>
            <div class="settings-row-control">
              <input
                type="password"
                class="form-input"
                id="settings-api-key"
                value="${escapeHtml(apiKey)}"
                autocomplete="new-password"
              />
            </div>
          </div>

          <div class="settings-row">
            <div class="settings-row-info">
              <label>URL base del API</label>
              <p>Dejar vacío para usar el mismo origen (recomendado). Útil si el UI está en otro dominio.</p>
            </div>
            <div class="settings-row-control">
              <input
                type="url"
                class="form-input"
                id="settings-base-url"
                value="${escapeHtml(baseUrl)}"
                placeholder="https://portal.aeisoftware.com"
                autocomplete="off"
              />
            </div>
          </div>
        </div>

        <div class="settings-section">
          <div class="settings-section-header">ℹ️ Información</div>
          <div class="settings-row">
            <div class="settings-row-info">
              <label>Versión del portal</label>
              <p>Versión de la API del backend</p>
            </div>
            <span class="badge badge-plan" id="settings-version">—</span>
          </div>
          <div class="settings-row">
            <div class="settings-row-info">
              <label>Documentación API interactiva</label>
              <p>Swagger UI para probar los endpoints directamente</p>
            </div>
            <a href="/docs" target="_blank" class="btn btn-sm btn-secondary">Abrir Docs ↗</a>
          </div>
        </div>

        <div class="flex gap-3">
          <button class="btn btn-primary" onclick="Settings.save()">💾 Guardar cambios</button>
          <button class="btn btn-danger" onclick="Settings.reset()">🗑 Restablecer</button>
        </div>
      </div>
    `;
  },

  // ── Skeleton loader ────────────────────────────────────────────────────────
  _skeleton() {
    return Array(4).fill(0).map(() => `
      <div class="card mb-4" style="margin-bottom:var(--sp-4)">
        <div class="flex gap-4 items-center">
          <div class="skeleton" style="width:42px;height:42px;border-radius:var(--radius);flex-shrink:0"></div>
          <div class="flex flex-col gap-2" style="flex:1">
            <div class="skeleton" style="height:14px;width:40%"></div>
            <div class="skeleton" style="height:12px;width:60%"></div>
          </div>
          <div class="skeleton" style="width:80px;height:26px;border-radius:var(--radius-full)"></div>
        </div>
      </div>
    `).join('');
  },
};

// =============================================================================
// SETTINGS actions
// =============================================================================
const Settings = {
  save() {
    const apiKey  = document.getElementById('settings-api-key')?.value.trim();
    const baseUrl = document.getElementById('settings-base-url')?.value.trim();
    if (apiKey)  Config.set('apiKey', apiKey);
    Config.set('baseUrl', baseUrl || '');
    Toast.success('Configuración guardada', 'Los nuevos valores están activos.');
    App.checkHealth();
  },
  reset() {
    localStorage.removeItem('saas_portal_apiKey');
    localStorage.removeItem('saas_portal_baseUrl');
    Toast.info('Configuración restablecida', 'Recargando…');
    setTimeout(() => location.reload(), 1000);
  },
  async loadVersion() {
    try {
      const data = await Api.health();
      const el = document.getElementById('settings-version');
      if (el) el.textContent = data.version || 'v1.1.0';
    } catch { /* ignore */ }
  },
};

// =============================================================================
// MODALS
// =============================================================================
const Modals = {
  _deleteTarget: null,

  openCreate() {
    document.getElementById('modal-create').classList.remove('hidden');
    CreateForm.reset();
    setTimeout(() => document.getElementById('input-tenant-id')?.focus(), 50);
  },
  closeCreate() {
    document.getElementById('modal-create').classList.add('hidden');
  },

  openDelete(tenantId) {
    Modals._deleteTarget = tenantId;
    document.getElementById('confirm-delete-subtitle').textContent =
      `Se eliminará el tenant "${tenantId}" y todos sus datos de Kubernetes y PostgreSQL.`;
    document.getElementById('modal-confirm-delete').classList.remove('hidden');
  },
  closeDelete() {
    document.getElementById('modal-confirm-delete').classList.add('hidden');
    Modals._deleteTarget = null;
  },

  closeSuccess() {
    document.getElementById('modal-success').classList.add('hidden');
    Store.setLastCreated(null);
  },

  openLogs(tenantId) {
    document.getElementById('modal-logs-subtitle').textContent = `Tenant: ${tenantId}`;
    document.getElementById('modal-log-content').textContent = 'Cargando…';
    document.getElementById('modal-logs').classList.remove('hidden');
    document.getElementById('modal-logs').dataset.tenant = tenantId;
    Actions.refreshLogs();
  },
  closeLogs() {
    document.getElementById('modal-logs').classList.add('hidden');
  },

  async openConfig(tenantId) {
    document.getElementById('modal-config-subtitle').textContent = `Tenant: ${tenantId}`;
    document.getElementById('modal-config-content').value = 'Cargando…';
    document.getElementById('modal-config').classList.remove('hidden');
    document.getElementById('modal-config').dataset.tenant = tenantId;
    try {
      const data = await Api.instances.config(tenantId);
      document.getElementById('modal-config-content').value = data.odoo_conf || '';
    } catch (e) {
      document.getElementById('modal-config-content').value = `# Error cargando configuración: ${e.detail}`;
    }
  },
  closeConfig() {
    document.getElementById('modal-config').classList.add('hidden');
  },
};

// =============================================================================
// CREATE FORM
// =============================================================================
const CreateForm = {
  _plan: 'starter',
  _checkTimer: null,
  _lastChecked: '',
  _available: false,

  reset() {
    document.getElementById('input-tenant-id').value = '';
    document.getElementById('input-tenant-id').className = 'form-input';
    document.getElementById('avail-indicator').innerHTML = '';
    document.getElementById('preview-url').textContent = '';
    document.getElementById('input-storage').value = 10;
    document.getElementById('storage-display').textContent = '10';
    document.getElementById('input-odoo-version').value = '18.0';
    document.getElementById('input-custom-image').value = '';
    document.getElementById('create-btn-text').textContent = 'Crear Tenant';
    document.getElementById('create-btn-icon').textContent = '✨';
    document.getElementById('btn-create-submit').disabled = false;
    this.selectPlan('starter');
    this._available = false;
    this._lastChecked = '';
  },

  selectPlan(plan) {
    this._plan = plan;
    ['starter', 'pro', 'enterprise'].forEach(p => {
      const el = document.getElementById(`plan-${p}`);
      if (el) el.classList.toggle('selected', p === plan);
    });
  },

  onStorageChange(val) {
    const el = document.getElementById('storage-display');
    if (el) el.textContent = val;
  },

  onTenantIdChange(val) {
    const baseDomain = window.location.hostname.replace(/^portal\./, '') || 'aeisoftware.com';
    const previewEl = document.getElementById('preview-url');
    if (previewEl) previewEl.textContent = val ? `${val}.${baseDomain}` : '';

    // Debounced availability check
    clearTimeout(this._checkTimer);
    if (!val || val.length < 2) {
      document.getElementById('avail-indicator').innerHTML = '';
      document.getElementById('input-tenant-id').className = 'form-input';
      return;
    }

    // Basic format validation
    if (!/^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$/.test(val)) {
      document.getElementById('input-tenant-id').className = 'form-input error';
      document.getElementById('avail-indicator').innerHTML =
        `<span class="form-error-text">Solo letras minúsculas, números y guiones (mín. 2 chars)</span>`;
      this._available = false;
      return;
    }

    document.getElementById('avail-indicator').innerHTML =
      `<span class="loading-spinner"></span><span class="text-muted" style="font-size:var(--text-xs)">Verificando…</span>`;

    this._checkTimer = setTimeout(() => this._checkAvailability(val), 500);
  },

  async _checkAvailability(id) {
    if (id === this._lastChecked) return;
    this._lastChecked = id;
    try {
      const res = await Api.instances.check(id);
      if (document.getElementById('input-tenant-id')?.value !== id) return; // stale
      if (res.available) {
        document.getElementById('input-tenant-id').className = 'form-input success';
        document.getElementById('avail-indicator').innerHTML =
          `<span class="form-success-text">✓ Disponible</span>`;
        this._available = true;
      } else {
        document.getElementById('input-tenant-id').className = 'form-input error';
        const reason = res.namespace_exists ? 'namespace ya existe' : 'base de datos ya existe';
        document.getElementById('avail-indicator').innerHTML =
          `<span class="form-error-text">✗ No disponible (${reason})</span>`;
        this._available = false;
      }
    } catch (e) {
      document.getElementById('avail-indicator').innerHTML =
        `<span class="text-muted" style="font-size:var(--text-xs)">No se pudo verificar</span>`;
      this._available = true; // optimistic — backend will reject on create if taken
    }
  },

  async submit() {
    const tenantId = document.getElementById('input-tenant-id').value.trim();
    const storage  = parseInt(document.getElementById('input-storage').value);
    const version  = document.getElementById('input-odoo-version').value;
    const image    = document.getElementById('input-custom-image').value.trim() || null;

    if (!tenantId) {
      Toast.error('ID requerido', 'Ingresa un ID para el tenant.');
      document.getElementById('input-tenant-id').focus();
      return;
    }
    if (!/^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$/.test(tenantId)) {
      Toast.error('ID inválido', 'Usa solo letras minúsculas, números y guiones.');
      return;
    }

    const btn = document.getElementById('btn-create-submit');
    btn.disabled = true;
    document.getElementById('create-btn-icon').textContent = '';
    document.getElementById('create-btn-icon').innerHTML = '<span class="loading-spinner"></span>';
    document.getElementById('create-btn-text').textContent = 'Aprovisionando…';

    try {
      const result = await Api.instances.create({
        tenant_id:    tenantId,
        plan:         this._plan,
        storage_gi:   storage,
        odoo_version: version,
        custom_image: image,
      });

      Modals.closeCreate();
      Store.setLastCreated(result);

      // Show success modal
      document.getElementById('success-url').textContent = result.url || '';
      document.getElementById('success-url').href = result.url || '#';
      document.getElementById('success-password').textContent = result.app_admin_password || 'N/D';
      document.getElementById('modal-success').classList.remove('hidden');

      Toast.success('Tenant creado', `"${tenantId}" está siendo aprovisionado.`);
      await App.loadTenants();

    } catch (e) {
      Toast.error('Error al crear tenant', e.detail || e.message);
      btn.disabled = false;
      document.getElementById('create-btn-icon').textContent = '✨';
      document.getElementById('create-btn-text').textContent = 'Crear Tenant';
    }
  },
};

// =============================================================================
// ACTIONS — API operations with feedback
// =============================================================================
const Actions = {
  async stop(tenantId) {
    try {
      await Api.instances.stop(tenantId);
      Toast.success('Tenant suspendido', `"${tenantId}" ha sido pausado.`);
      await App.loadTenants();
      if (Store.currentView === 'tenantDetail') App.renderView();
    } catch (e) {
      Toast.error('Error al suspender', e.detail || e.message);
    }
  },

  async start(tenantId) {
    try {
      await Api.instances.start(tenantId);
      Toast.success('Tenant iniciado', `"${tenantId}" está iniciando.`);
      await App.loadTenants();
      if (Store.currentView === 'tenantDetail') App.renderView();
    } catch (e) {
      Toast.error('Error al iniciar', e.detail || e.message);
    }
  },

  async confirmDelete() {
    const id = Modals._deleteTarget;
    if (!id) return;

    const btn = document.getElementById('btn-confirm-delete');
    btn.disabled = true;
    btn.textContent = 'Eliminando…';

    try {
      await Api.instances.delete(id);
      Modals.closeDelete();
      Toast.success('Tenant eliminado', `"${id}" ha sido eliminado.`);

      // If we're on detail of deleted tenant, go back
      if (Store.selectedId === id) {
        App.navigate('tenants');
      }
      await App.loadTenants();
    } catch (e) {
      Toast.error('Error al eliminar', e.detail || e.message);
      btn.disabled = false;
      btn.textContent = 'Sí, eliminar';
    }
  },

  async refreshLogs() {
    const modal    = document.getElementById('modal-logs');
    const tenantId = modal?.dataset.tenant;
    const lines    = parseInt(document.getElementById('log-lines-select')?.value || '200');
    const el       = document.getElementById('modal-log-content');
    if (!tenantId || !el) return;

    el.textContent = 'Cargando…';
    try {
      const data = await Api.instances.logs(tenantId, lines);
      el.innerHTML = colorizeLog(escapeHtml(data.logs || 'Sin logs disponibles.'));
      // Auto-scroll to bottom
      el.scrollTop = el.scrollHeight;
    } catch (e) {
      el.textContent = `Error cargando logs: ${e.detail || e.message}`;
    }
  },

  copyLogs() {
    const text = document.getElementById('modal-log-content')?.textContent || '';
    navigator.clipboard.writeText(text)
      .then(() => Toast.success('Copiado', 'Logs copiados al portapapeles.'))
      .catch(() => Toast.error('Error', 'No se pudo copiar.'));
  },

  copyPassword() {
    const text = document.getElementById('success-password')?.textContent || '';
    navigator.clipboard.writeText(text)
      .then(() => Toast.success('Copiado', 'Contraseña copiada.'))
      .catch(() => Toast.error('Error', 'No se pudo copiar.'));
  },

  openLogs(tenantId) { Modals.openLogs(tenantId); },
  openConfig(tenantId) { Modals.openConfig(tenantId); },

  async saveConfig() {
    const modal    = document.getElementById('modal-config');
    const tenantId = modal?.dataset.tenant;
    const conf     = document.getElementById('modal-config-content')?.value;
    if (!tenantId) return;

    const btn = document.getElementById('btn-save-config');
    btn.disabled = true;
    btn.textContent = 'Guardando…';

    try {
      await Api.instances.saveConfig(tenantId, { odoo_conf: conf });
      Modals.closeConfig();
      Toast.success('Configuración guardada', `"${tenantId}" se está reiniciando.`);
    } catch (e) {
      Toast.error('Error al guardar', e.detail || e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '💾 Guardar y Reiniciar';
    }
  },

  goToNewTenant() {
    const id = Store.lastCreated?.tenant_id;
    Modals.closeSuccess();
    if (id) App.openTenant(id);
  },
};

// =============================================================================
// APP — router, data loader, render orchestrator
// =============================================================================
const App = {
  _pollingTimer: null,

  async init() {
    // Search input
    const searchEl = document.getElementById('global-search');
    if (searchEl) {
      let st;
      searchEl.addEventListener('input', e => {
        clearTimeout(st);
        st = setTimeout(() => {
          Store.setSearchQuery(e.target.value);
          if (Store.currentView !== 'create' && Store.currentView !== 'settings') {
            App.renderView();
          }
        }, 200);
      });
    }

    // Keyboard shortcut: Escape closes modals
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        ['modal-create','modal-confirm-delete','modal-success','modal-logs','modal-config'].forEach(id => {
          document.getElementById(id)?.classList.add('hidden');
        });
      }
    });

    // Backdrop click closes modals
    document.querySelectorAll('.modal-backdrop').forEach(el => {
      el.addEventListener('click', function(e) {
        if (e.target === this) this.classList.add('hidden');
      });
    });

    await this.checkHealth();
    await this.loadTenants();
    this.navigate('dashboard');
    this._startPolling();
  },

  async checkHealth() {
    const dot  = document.getElementById('cluster-dot');
    const text = document.getElementById('cluster-status-text');
    try {
      await Api.health();
      if (dot)  { dot.className = 'cluster-dot ok'; }
      if (text) { text.textContent = 'Portal OK'; }
    } catch {
      if (dot)  { dot.className = 'cluster-dot error'; }
      if (text) { text.textContent = 'Sin conexión'; }
    }
  },

  async loadTenants(showLoading = false) {
    if (showLoading) Store.setLoading(true);
    try {
      const tenants = await Api.instances.list();
      Store.setTenants(Array.isArray(tenants) ? tenants : []);

      // Update nav badge
      const badge = document.getElementById('nav-tenants-count');
      if (badge) {
        const count = tenants.length;
        badge.textContent = count;
        badge.style.display = count > 0 ? '' : 'none';
      }
    } catch (e) {
      // Show error but don't clear existing tenants
      if (Store.tenants.length === 0) Store.setTenants([]);
    } finally {
      Store.setLoading(false);
    }
  },

  navigate(view, tenantId = null) {
    Store.setView(view);
    if (tenantId) Store.setSelectedId(tenantId);

    // Update nav active state
    ['dashboard','tenants','create','settings'].forEach(v => {
      const el = document.getElementById(`nav-${v}`);
      if (el) el.classList.toggle('active', v === view);
    });

    this.renderView();
  },

  openTenant(tenantId) {
    Store.setSelectedId(tenantId);
    Store.setView('tenantDetail');
    ['dashboard','tenants','create','settings'].forEach(v => {
      document.getElementById(`nav-${v}`)?.classList.remove('active');
    });
    this.renderView();
  },

  renderView() {
    const main = document.getElementById('main-content');
    if (!main) return;

    const view = Store.currentView;

    if (view === 'dashboard') {
      main.innerHTML = Views.dashboard();
    } else if (view === 'tenants') {
      main.innerHTML = Views.tenants();
    } else if (view === 'tenantDetail') {
      const tenant = Store.getTenant(Store.selectedId);
      main.innerHTML = Views.tenantDetail(tenant);
    } else if (view === 'create') {
      main.innerHTML = Views.create();
    } else if (view === 'settings') {
      main.innerHTML = Views.settings();
      Settings.loadVersion();
    }
  },

  async refresh() {
    const btn = document.getElementById('btn-refresh');
    if (btn) { btn.style.animation = 'spin 0.5s linear'; }
    await this.checkHealth();
    await this.loadTenants();
    this.renderView();
    if (btn) { setTimeout(() => { btn.style.animation = ''; }, 600); }
    Toast.info('Actualizado', 'Datos refrescados desde el servidor.');
  },

  async refreshDetail(tenantId) {
    try {
      const fresh = await Api.instances.get(tenantId);
      // Update in store
      const idx = Store.tenants.findIndex(t => t.tenant_id === tenantId);
      if (idx >= 0) {
        const updated = [...Store.tenants];
        updated[idx] = fresh;
        Store.setTenants(updated);
      }
      this.renderView();
    } catch (e) {
      Toast.error('Error al actualizar', e.detail || e.message);
    }
  },

  _startPolling() {
    // Poll every 15s to update tenant statuses
    this._pollingTimer = setInterval(async () => {
      if (document.hidden) return; // Don't poll when tab is hidden
      await this.loadTenants();
      // Only re-render if on a data-dependent view
      const v = Store.currentView;
      if (v === 'dashboard' || v === 'tenants' || v === 'tenantDetail') {
        this.renderView();
      }
    }, 15_000);
  },
};

// =============================================================================
// BOOTSTRAP
// =============================================================================
document.addEventListener('DOMContentLoaded', () => App.init());
