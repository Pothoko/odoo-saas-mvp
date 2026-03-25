"""
models/sale_order.py

When the eCommerce cart already contains a SaaS subscription product and the
customer tries to add another one, the purchase is *allowed* but a warning
message is injected into the cart-update response so the frontend can display
a toast notification.
"""
import logging
from odoo import models, _

logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _cart_update(self, product_id, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """Allow multiple SaaS products but warn the customer."""
        product = self.env["product.product"].browse(product_id)
        saas_categ = self.env.ref(
            "odoo_k8s_saas.product_category_odoo_saas", raise_if_not_found=False
        )

        def _is_saas(prod):
            """Return True if prod belongs to the SaaS category."""
            if not prod:
                return False
            if saas_categ:
                categ = prod.categ_id
                while categ:
                    if categ.id == saas_categ.id:
                        return True
                    categ = categ.parent_id
            # Fallback: name-based detection
            return "saas" in (prod.name or "").lower()

        # Detect whether there is already a SaaS product in the cart
        warning = False
        if _is_saas(product):
            for line in self.order_line:
                # Ignore qty changes on the same line
                if line.product_id.id == product_id and line.id == line_id:
                    continue
                if _is_saas(line.product_id):
                    warning = _(
                        "Ya tienes un plan SaaS en tu carrito. "
                        "Cada compra generará una suscripción independiente "
                        "con su propio número de contrato."
                    )
                    break

        # Always let the purchase proceed
        result = super()._cart_update(
            product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, **kwargs
        )

        if warning and isinstance(result, dict):
            result["warning"] = warning

        return result
