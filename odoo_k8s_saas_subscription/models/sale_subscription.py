"""
models/sale_subscription.py

Subscription lifecycle hooks for SaaS provisioning/suspension.

Stage transitions:
  → In Progress : provision the linked saas.instance (if not already)
  → Closed      : delete/suspend the linked saas.instance
"""
import logging

from odoo import models

logger = logging.getLogger(__name__)

# Stage XML IDs from subscription_oca
_STAGE_IN_PROGRESS = "subscription_oca.stage_in_progress"
_STAGE_CLOSED = "subscription_oca.stage_closed"


class SaleSubscription(models.Model):
    _inherit = "sale.subscription"

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
