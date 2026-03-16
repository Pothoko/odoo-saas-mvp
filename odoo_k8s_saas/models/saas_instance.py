"""
models/saas_instance.py

Tracks SaaS tenant instances as Odoo records.
Calls the portal API to provision / deprovision.
No dependency on sale, contract, or subscription modules.
"""
import logging
import os
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

PORTAL_URL = os.getenv("SAAS_PORTAL_URL", "http://portal.aeisoftware.svc.cluster.local:8000")
PORTAL_KEY = os.getenv("SAAS_PORTAL_KEY", "")


class SaasInstance(models.Model):
    _name = "saas.instance"
    _description = "SaaS Tenant Instance"
    _order = "create_date desc"

    name = fields.Char(string="Instance Name", required=True, help="Human-readable name")
    tenant_id = fields.Char(
        string="Tenant ID", required=True, index=True,
        help="Slug used as subdomain: e.g. 'demo' → demo.aeisoftware.com",
    )
    url = fields.Char(string="URL", readonly=True)
    namespace = fields.Char(string="K8s Namespace", readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("provisioning", "Provisioning"),
            ("ready", "Ready"),
            ("error", "Error"),
            ("deleted", "Deleted"),
        ],
        default="draft", required=True, tracking=True,
    )
    plan = fields.Selection(
        [("starter", "Starter"), ("pro", "Pro"), ("enterprise", "Enterprise")],
        default="starter", required=True,
    )
    storage_gi = fields.Integer(string="Storage (GB)", default=10)
    error_msg = fields.Text(string="Error", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer")

    # ── actions ───────────────────────────────────────────────────────────────

    def action_provision(self):
        self.ensure_one()
        if self.state not in ("draft", "error"):
            raise UserError("Can only provision from Draft or Error state.")
        try:
            resp = requests.post(
                f"{PORTAL_URL}/api/v1/instances",
                json={
                    "tenant_id": self.tenant_id,
                    "plan": self.plan,
                    "storage_gi": self.storage_gi,
                },
                headers={"X-API-Key": PORTAL_KEY},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self.write({
                "state": "provisioning",
                "url": data.get("url"),
                "namespace": data.get("namespace"),
                "error_msg": False,
            })
        except Exception as exc:
            self.write({"state": "error", "error_msg": str(exc)})
            raise UserError(f"Provisioning failed: {exc}") from exc

    def action_check_status(self):
        """Refresh state from portal — useful from buttons or cron."""
        for rec in self.filtered(lambda r: r.state in ("provisioning",)):
            try:
                resp = requests.get(
                    f"{PORTAL_URL}/api/v1/instances/{rec.tenant_id}",
                    headers={"X-API-Key": PORTAL_KEY},
                    timeout=10,
                )
                if resp.status_code == 404:
                    rec.state = "deleted"
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "ready":
                    rec.state = "ready"
            except Exception as exc:
                logger.warning("Status check failed for %s: %s", rec.tenant_id, exc)

    def action_delete(self):
        self.ensure_one()
        try:
            resp = requests.delete(
                f"{PORTAL_URL}/api/v1/instances/{self.tenant_id}",
                headers={"X-API-Key": PORTAL_KEY},
                timeout=30,
            )
            if resp.status_code not in (204, 404):
                resp.raise_for_status()
            self.state = "deleted"
        except Exception as exc:
            self.write({"state": "error", "error_msg": str(exc)})
            raise UserError(f"Delete failed: {exc}") from exc
