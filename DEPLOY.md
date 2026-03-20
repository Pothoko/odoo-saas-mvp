# DEPLOY — odoo-saas-mvp

## Entorno

| Elemento | Valor |
|---|---|
| Namespace K8s | `odoo-admin` |
| Deployment | `odoo-admin` |
| Label selector | `app=odoo-admin` |
| Base de datos Odoo | `postgres` |
| DB filter | `^admin$` |
| Repo en initContainer | `https://github.com/jpvargassoruco/odoo-saas-mvp.git` (branch `main`) |

---

## Flujo de despliegue estándar

```bash
# 1. Commit y push del código
git add <archivos>
git commit -m "tipo(módulo): descripción"
git push origin main

# 2. Restart del deployment
#    El initContainer clona el repo actualizado automáticamente
kubectl rollout restart deployment/odoo-admin -n odoo-admin

# 3. Esperar a que el pod esté Running
kubectl rollout status deployment/odoo-admin -n odoo-admin
```

---

## Cuando hay cambios de esquema BD (campos nuevos en modelos)

> Requerido tras agregar `fields.*` a cualquier modelo Odoo.

```bash
# 3a. Obtener nombre del pod
POD=$(kubectl get pod -n odoo-admin -l app=odoo-admin -o jsonpath='{.items[0].metadata.name}')

# 3b. Ejecutar update del módulo (crea columnas nuevas en PostgreSQL)
kubectl exec -n odoo-admin $POD -- \
  odoo -u payment_qr_mercantil -d postgres --stop-after-init

# 3c. Restart limpio
kubectl rollout restart deployment/odoo-admin -n odoo-admin
kubectl rollout status deployment/odoo-admin -n odoo-admin
```

Para actualizar **todos** los módulos del repo:
```bash
kubectl exec -n odoo-admin $POD -- \
  odoo -u all -d postgres --stop-after-init
```

---

## Verificar logs en tiempo real

```bash
POD=$(kubectl get pod -n odoo-admin -l app=odoo-admin -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n odoo-admin $POD -f
```

---

## Módulos del repo

| Módulo | Descripción |
|---|---|
| `payment_qr_mercantil` | Pago por QR — Banco Mercantil Santa Cruz (mc4.com.bo) |
| `odoo_k8s_saas_subscription` | Gestión de suscripciones SaaS sobre K8s |

---

## Notas

- El initContainer `alpine/git` clona `main` con `--depth=1` en cada restart.  
  **No hay CI/CD automático** — el restart debe hacerse manualmente después del push.
- El flag `-u` **no** se ejecuta automáticamente en el entrypoint.  
  Siempre correrlo manualmente tras cambios de esquema.
- La BD `postgres` es la instancia admin; las BD de clientes SaaS son dinamicas (ver `odoo_k8s_saas_subscription`).
