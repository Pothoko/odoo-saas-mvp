"""
models/sale_order.py

Extends the subscription creation flow from subscription_oca.
When a sale order is confirmed and subscriptions are created,
also create linked saas.instance records for SaaS products.
"""
import logging
import re

from odoo import models

logger = logging.getLogger(__name__)

SAAS_CATEGORY_XMLID = "odoo_k8s_saas.product_category_odoo_saas"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        """After SO confirmation + subscription creation, link SaaS instances."""
        res = super().action_confirm()

        saas_category = self.env.ref(SAAS_CATEGORY_XMLID, raise_if_not_found=False)
        if not saas_category:
            # Fallback name search
            saas_category = self.env["product.category"].search(
                [("name", "ilike", "odoo%saas")], limit=1
            )
        if not saas_category:
            return res

        Instance = self.env["saas.instance"]

        for order in self:
            # Check if any SO lines are in the SaaS category OR have "saas" in the name
            saas_lines = order.order_line.filtered(
                lambda l: l.product_id
                and (
                    (l.product_id.categ_id and saas_category and self._is_saas_category(l.product_id.categ_id, saas_category))
                    or "saas" in (l.product_id.name or "").lower()
                )
            )
            if not saas_lines:
                continue

            # Find subscriptions created for this order by subscription_oca
            subscriptions = self.env["sale.subscription"].search([
                ("sale_order_id", "=", order.id),
            ])
            if not subscriptions:
                logger.info(
                    "SaaS-Sub bridge: SO %s has SaaS lines but no subscription "
                    "(product may not be subscribable) — skipping.",
                    order.name,
                )
                continue

            for subscription in subscriptions:
                # Skip if instance already exists for this subscription
                existing = Instance.search([
                    ("subscription_id", "=", subscription.id),
                    ("state", "not in", ["deleted"]),
                ], limit=1)
                if existing:
                    logger.info(
                        "Instance already exists for subscription %s: %s",
                        subscription.display_name, existing.tenant_id,
                    )
                    continue

                tenant_id = self._generate_saas_tenant_id(order.partner_id)

                # Determine plan from subscription template name (if available)
                plan = "starter"
                if subscription.template_id:
                    tmpl_name = (subscription.template_id.name or "").lower()
                    if "enterprise" in tmpl_name:
                        plan = "enterprise"
                    elif "pro" in tmpl_name:
                        plan = "pro"

                storage_map = {"starter": 10, "pro": 50, "enterprise": 100}

                instance = Instance.create({
                    "name": f"{order.partner_id.name} — {order.name}",
                    "tenant_id": tenant_id,
                    "plan": plan,
                    "storage_gi": storage_map.get(plan, 10),
                    "partner_id": order.partner_id.id,
                    "sale_order_id": order.id,
                    "subscription_id": subscription.id,
                })
                logger.info(
                    "SaaS-Sub bridge: created instance %s linked to subscription %s",
                    instance.tenant_id, subscription.display_name,
                )

        return res

    def _generate_saas_tenant_id(self, partner):
        """Generate a URL-safe tenant_id from partner name + sequence."""
        slug = re.sub(r"[^a-z0-9]+", "-", (partner.name or "tenant").lower()).strip("-")
        slug = slug[:30].rstrip("-")
        seq = self.env["ir.sequence"].next_by_code("saas.tenant.id") or "001"
        return f"{slug}-{seq}"

    def _is_saas_category(self, categ, saas_categ):
        """Return True if categ is saas_categ or a child of it."""
        while categ:
            if categ.id == saas_categ.id:
                return True
            categ = categ.parent_id
        return False
