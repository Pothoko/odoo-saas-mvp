# QA del flujo de compras

**Fecha:** 2026-05-12
**Rama:** `main` (staging)
**Alcance:** checkout web (`/shop`, `/shop/cart`, `/shop/checkout`, `/shop/address`),
pasarela QR Mercantil (`/payment/qr_mercantil/*`), bridge `sale.subscription` →
`saas.instance` y guards de carrito.

---

## 1. Componentes auditados

| Capa | Archivo | Función |
|------|---------|---------|
| Override de plantilla | `odoo_k8s_saas_subscription/views/checkout_address_override.xml` | Oculta street/city/zip/state y reduce `required_fields` a 5 |
| Controlador checkout | `odoo_k8s_saas_subscription/controllers/website_sale_guard.py` | Redirige guests a login + sobrescribe `_get_mandatory_billing_address_fields` + filtra `shop_country_info` |
| Config tienda | `odoo_k8s_saas_subscription/data/website_checkout_config.xml` | `account_on_checkout = mandatory` |
| Guard del carrito | `odoo_k8s_saas_subscription/models/sale_order.py` | Inyecta `warning` en respuesta de `/shop/cart/update_json` |
| Toast + Bolivia + observer | `odoo_k8s_saas_subscription/static/src/js/cart_warning.js` | Tres IIFE: interceptor XHR, pre-select Bolivia, `MutationObserver` de `required` |
| QR Mercantil — provider | `payment_qr_mercantil/models/payment_provider.py` | Token JWT cacheado en DB + lock por proceso |
| QR Mercantil — tx | `payment_qr_mercantil/models/payment_transaction.py` | `_get_specific_rendering_values`, `_process_notification_data` |
| QR Mercantil — controllers | `payment_qr_mercantil/controllers/main.py` | `/display`, `/webhook`, `/status` (throttle 10 s DB), `/simulate` |
| QR Mercantil — frontend | `payment_qr_mercantil/static/src/js/qr_mercantil_form.js` | Polling 3 s + simulate button con guard de reentrada |
| Bridge suscripciones | `odoo_k8s_saas_subscription/models/sale_subscription.py` | Hooks `write()` sobre `stage_id`, `template_id`, `recurring_next_date` |

---

## 2. Resultados ✅

### 2.1 Formulario de dirección (5 campos requeridos)

Defensa en profundidad multicapa para Bolivia:

1. **CSS `display:none`** sobre `#div_street`, `#div_street2`, `#div_city`, `#div_zip` y wrapper de `state_id` (`checkout_address_override.xml:27-58`).
2. **Pre-fill** de los inputs ocultos con `partner_sudo.street or '-'`, `city or '-'`, `zip or '0000'` para que la validación server-side siempre pase.
3. **`required_fields`** reducido a `name,email,phone,company_name,vat,country_id` con selector `(//input[@name='required_fields'])[1]` para evitar matchear `address_on_payment`.
4. **`_get_mandatory_billing_address_fields`** override directo en `WebsiteSaleSaaSGuard` (`website_sale_guard.py:49-52`) — Odoo 18 entry point.
5. **`shop_country_info`** filtra `street/city/zip/state_id` de `fields` y `required_fields` para que `address.js` haga `_hideInput` y no los re-muestre al cambiar país (`website_sale_guard.py:55-64`).
6. **`MutationObserver` por-elemento** en JS limpia el atributo `required` cada vez que Odoo lo reasigna dinámicamente (`cart_warning.js:109-143`).

### 2.2 Bolivia pre-seleccionado

`MutationObserver` global sobre `#o_country_id` con `option[code="BO"]` y `dispatchEvent("change")` — funciona aunque Odoo 18 renderice el form vía XHR/interactions (`cart_warning.js:86-104`).

### 2.3 Cuenta obligatoria

`account_on_checkout = mandatory` aplicado por `website_checkout_config.xml`. Combinado con:
- `WebsiteSaleSaaSGuard.checkout()` que redirige a `/web/login?redirect=/shop/checkout` si el usuario es público y hay SaaS en el carrito (`website_sale_guard.py:21-32`).
- `SaleOrder._cart_update` que inyecta un `warning` en la respuesta JSON con aviso de login para guests + aviso multi-SaaS (`sale_order.py:38-70`).
- Toast vanilla que intercepta XHR `/shop/cart/update` y linkifica "iniciar sesión / crear una cuenta" con redirect-back (`cart_warning.js:7-81`).

### 2.4 QR Mercantil

- **Token JWT** cacheado en DB para compartir entre workers + `_TOKEN_LOCK` por proceso + margen de refresh 5 min (`payment_provider.py:120-179`).
- **Frontend polling cada 3 s** (`qr_mercantil_form.js:10`), **server throttle 10 s** al banco usando `SELECT … FOR UPDATE SKIP LOCKED` para que solo un worker consulte por tx (`controllers/main.py:194-227`).
- **Modo demo**: `provider.state == 'test'` → QR ficticio SVG + botón "Simular Pago" con guard `isSimulating` síncrono contra doble click (`qr_mercantil_form.js:96-100`).
- **Webhook** llama `_handle_notification_data → _set_done` (`payment_transaction.py:130-159`).
- **Mapeo de estados "pagado"** robusto a variantes del banco (`_PAID_STATES` incluye PAGADO/EJECUTADO/APROBADO/COMPLETADO/etc, `controllers/main.py:10-14`).

### 2.5 Bridge suscripción → SaaS instance (`sale_subscription.py:251-518`)

- **Stage → In Progress**: crea una `saas.instance` **por línea SaaS** del pedido, con sufijo `odoo_version` si hay varias. Idempotencia doble (por `sale_order_line_id` y por `tenant_id`).
- **Stage → Closed**: suspende y registra `closed_date`; cron `_cron_sync_closed_subscriptions` aplica grace period (`SAAS_GRACE_PERIOD_DAYS`, default 7 días) y luego invoca `action_request_delete`.
- **Cambio `template_id`** (upgrade/downgrade): actualiza recursos K8s (`action_upgrade`) **y** reemplaza la línea de facturación al producto del nuevo template, con fallback por categoría SaaS.
- **Dunning escalado** (`_cron_suspend_overdue`): emails en +1 día, +3 días y suspensión efectiva en +5 días. Reset automático cuando `recurring_next_date` avanza (pago recibido).
- **Re-provision manual** (`action_reprovision_instance`) — útil si una instancia fue borrada accidentalmente.

### 2.6 Sanity runtime

Probado sobre `https://staging.aeisoftware.com`:

| Endpoint | Resultado | Esperado |
|---|---|---|
| `GET /shop` | `200` con 9 productos SaaS (3 planes × 3 versiones) + Soporte | ✓ |
| `GET /shop/checkout` (sin carrito) | `303 → /shop` | ✓ (Odoo redirige sin carrito) |
| `GET /payment/qr_mercantil/display?reference=NOEXISTE` | `303 → /payment/status` | ✓ (`controllers/main.py:32-43`) |
| `POST /payment/qr_mercantil/status` (ref inexistente) | `200 {state: error}` | ✓ |
| `@import` en `portal_aei.css` | ausente | ✓ (fix `0432b2f`) |

---

## 3. Hallazgos ⚠️

### 3.1 Drift de documentación — intervalo de polling

**Severidad:** baja (doc).
`CLAUDE.md` describe "2s polling on frontend"; el código real es 3000 ms en `qr_mercantil_form.js:10`. Actualizar uno de los dos para que coincidan.

### 3.2 Webhook QR sin firma ni allowlist

**Severidad:** media.
`/payment/qr_mercantil/webhook` (`controllers/main.py:60-79`) está como `auth='public'`, `csrf=False` y **no verifica origen ni firma**. Cualquiera que conozca un `alias` puede llamarlo y disparar `_set_done`.

- El `alias` actual es el `reference` Odoo (UUID-like), lo cual mitiga el riesgo de enumeración, pero no lo elimina si el reference se loguea o aparece en URLs.
- Validar con Banco Mercantil si su API ofrece HMAC en el callback o lista de IPs fijas, e implementar la validación correspondiente.

### 3.3 Webhook no responde JSON en path éxito

**Severidad:** baja.
La ruta `webhook()` solo hace `return` en el `except`. En éxito el helper de `type='json'` serializa `None` como `null`. Devolver explícitamente `{'status': 'ok'}` ayuda al banco a confirmar la entrega y simplifica debugging.

### 3.4 `simulate_payment` con `auth='public'`

**Severidad:** baja (sólo en entornos de prueba).
Protegido únicamente por `provider_id.state == 'test'` (`controllers/main.py:106-111`). Correcto en producción porque el provider activo no está en `state='test'`, pero si alguna vez se deja un provider de test publicado en internet, cualquiera con la `reference` puede marcar la transacción como pagada. No requiere acción ahora, sólo recordatorio operativo: **no exponer providers en estado test a la web pública**.

### 3.5 `t-att-value` en `<input name="zip">` sobre-escribe la entrada del usuario

**Severidad:** muy baja (no aplicable mientras el div esté oculto).
Si en el futuro se muestra el campo zip, cada re-render del form (XHR de cambio de país) volverá a poner `partner_sudo.zip or '0000'` perdiendo lo que el usuario haya tecleado.

### 3.6 `MutationObserver` global con `subtree:true`

**Severidad:** muy baja (performance).
`cart_warning.js` engancha tres observers a `document.body` con `childList:true, subtree:true`. En páginas con mucha actividad DOM esto invocará `_scan`/`_attachObservers` con frecuencia. Está gateado por `el._saasOptWatched` y `sel.value`, así que el costo real es bajo, pero conviene tenerlo presente si se observan stutters en mobile.

---

## 4. Recomendaciones priorizadas

1. **🔴 Pedir a Banco Mercantil documentación del callback** y, si existe HMAC/firma, validarla en `webhook()`. Si no existe, considerar tokenizar el callback URL con un secret rotable (`/payment/qr_mercantil/webhook/<secret>` configurable por env var).
2. **🟡 Sincronizar `CLAUDE.md` con `POLL_INTERVAL_MS`** (3 s, no 2 s) o cambiar el JS a 2000 si esa era la intención original.
3. **🟢 Devolver `{'status': 'ok'}` explícito** desde `webhook()` en path éxito.
4. **🟢 Documentar en `DEPLOY.md`** que `provider.state = 'test'` **nunca** debe quedar activo en producción y que existe el endpoint `/payment/qr_mercantil/simulate` que confía en ese flag.

---

## 5. Conclusión

El flujo de compras está **bien blindado para el caso Bolivia**:

- 5 campos requeridos con seis capas de defensa (CSS + pre-fill + required_fields + override server + filtro country_info + observer JS).
- Cuenta obligatoria reforzada con guard de controller, aviso visual en cart y aviso al checkout.
- Pasarela QR con throttle DB anti-thundering-herd, modo demo limpio y polling resiliente.
- Bridge `subscription → saas.instance` con idempotencia robusta, dunning escalado y grace period.

**El único riesgo abierto no trivial es la falta de autenticación del webhook QR**; el resto son drifts de documentación o detalles cosméticos sin impacto funcional.
