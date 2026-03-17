"""
models/sale_subscription.py

Subscription lifecycle hooks for SaaS provisioning/suspension,
portal.mixin for customer-facing /my/subscriptions portal,
and re-provision action when an instance is manually deleted.

Stage transitions:
  → In Progress : provision the linked saas.instance (if not already)
  → Closed      : delete/suspend the linked saas.instance
"""
import logging
import re

from odoo import models, fields, api, _
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)

# Stage XML IDs from subscription_oca
_STAGE_IN_PROGRESS = "subscription_oca.stage_in_progress"
_STAGE_CLOSED = "subscription_oca.stage_closed"


class SaleSubscription(models.Model):
    _inherit = ["sale.subscription", "portal.mixin"]
    _name = "sale.subscription"

    # ── Computed fields ─────────────────────────────────────────
    saas_instance_count = fields.Integer(
        string="SaaS Instances",
        compute="_compute_saas_instance_count",
    )
    has_active_instance = fields.Boolean(
        compute="_compute_saas_instance_count",
    )

    @api.depends_context("uid")
    def _compute_saas_instance_count(self):
        Instance = self.env["saas.instance"]
        for rec in self:
            instances = Instance.search([
                ("subscription_id", "=", rec.id),
                ("state", "not in", ["deleted"]),
            ])
            rec.saas_instance_count = len(instances)
            rec.has_active_instance = bool(instances)

    # ── Portal mixin ────────────────────────────────────────────
    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = f"/my/subscriptions/{rec.id}"

    # ── Actions ─────────────────────────────────────────────────
    def action_view_saas_instances(self):
        """Open a list of linked SaaS instances."""
        self.ensure_one()
        instances = self.env["saas.instance"].search([
            ("subscription_id", "=", self.id),
        ])
        action = {
            "type": "ir.actions.act_window",
            "name": _("SaaS Instances"),
            "res_model": "saas.instance",
            "view_mode": "list,form",
            "domain": [("id", "in", instances.ids)],
            "context": {"default_subscription_id": self.id},
        }
        if len(instances) == 1:
            action["view_mode"] = "form"
            action["res_id"] = instances.id
        return action

    def action_reprovision_instance(self):
        """Re-create and provision a saas.instance when the old one was deleted."""
        self.ensure_one()

        # Guard: subscription must be "In Progress"
        stage_in_progress = self.env.ref(_STAGE_IN_PROGRESS, raise_if_not_found=False)
        if stage_in_progress and self.stage_id.id != stage_in_progress.id:
            raise UserError(
                _("You can only re-provision an instance for subscriptions "
                  "that are in the 'In Progress' stage.")
            )

        # Guard: must not already have an active instance
        existing = self.env["saas.instance"].search([
            ("subscription_id", "=", self.id),
            ("state", "not in", ["deleted"]),
        ], limit=1)
        if existing:
            raise UserError(
                _("This subscription already has an active instance: %s.\n"
                  "Delete it first if you want to re-provision.")
                % existing.tenant_id
            )

        # Generate a new tenant ID
        partner = self.partner_id
        slug = re.sub(r"[^a-z0-9]+", "-", (partner.name or "tenant").lower()).strip("-")
        slug = slug[:30].rstrip("-")
        seq = self.env["ir.sequence"].next_by_code("saas.tenant.id") or "001"
        tenant_id = f"{slug}-{seq}"

        # Determine plan from subscription template name
        plan = "starter"
        if self.template_id:
            tmpl_name = (self.template_id.name or "").lower()
            if "enterprise" in tmpl_name:
                plan = "enterprise"
            elif "pro" in tmpl_name:
                plan = "pro"

        storage_map = {"starter": 10, "pro": 50, "enterprise": 100}

        instance = self.env["saas.instance"].create({
            "name": f"{partner.name} — Re-provision ({self.display_name})",
            "tenant_id": tenant_id,
            "plan": plan,
            "storage_gi": storage_map.get(plan, 10),
            "partner_id": partner.id,
            "sale_order_id": self.sale_order_id.id if self.sale_order_id else False,
            "subscription_id": self.id,
        })

        logger.info(
            "Re-provisioned instance %s for subscription %s",
            instance.tenant_id, self.display_name,
        )

        # Auto-provision it
        try:
            instance.action_provision()
        except Exception:
            logger.exception(
                "Auto-provision failed for re-provisioned instance %s",
                instance.tenant_id,
            )

        # Return the instance form view
        return {
            "type": "ir.actions.act_window",
            "name": _("Re-provisioned Instance"),
            "res_model": "saas.instance",
            "view_mode": "form",
            "res_id": instance.id,
        }

    # ── Stage-change hooks ──────────────────────────────────────
    def write(self, vals):
        """Detect stage_id changes and trigger SaaS actions."""
        old_stages = {rec.id: rec.stage_id.id for rec in self}
        res = super().write(vals)

        if "stage_id" not in vals:
            return res

        new_stage_id = vals["stage_id"]

        # Resolve known stage IDs
        stage_in_progress = self.env.ref(_STAGE_IN_PROGRESS, raise_if_not_found=False)
        stage_closed = self.env.ref(_STAGE_CLOSED, raise_if_not_found=False)

        for rec in self:
            old_stage_id = old_stages.get(rec.id)
            if old_stage_id == new_stage_id:
                continue  # no change

            # Find linked SaaS instances
            instances = self.env["saas.instance"].search([
                ("subscription_id", "=", rec.id),
                ("state", "not in", ["deleted"]),
            ])
            if not instances:
                continue

            # → In Progress: provision
            if stage_in_progress and new_stage_id == stage_in_progress.id:
                for inst in instances.filtered(lambda i: i.state in ("draft", "error")):
                    logger.info(
                        "Subscription %s → In Progress: provisioning instance %s",
                        rec.display_name, inst.tenant_id,
                    )
                    try:
                        inst.action_provision()
                    except Exception:
                        logger.exception(
                            "Failed to provision %s from subscription %s",
                            inst.tenant_id, rec.display_name,
                        )

            # → Closed: delete/suspend
            elif stage_closed and new_stage_id == stage_closed.id:
                for inst in instances.filtered(
                    lambda i: i.state in ("draft", "provisioning", "ready")
                ):
                    logger.info(
                        "Subscription %s → Closed: deleting instance %s",
                        rec.display_name, inst.tenant_id,
                    )
                    try:
                        inst.action_delete()
                    except Exception:
                        logger.exception(
                            "Failed to delete %s from subscription %s",
                            inst.tenant_id, rec.display_name,
                        )

        return res

