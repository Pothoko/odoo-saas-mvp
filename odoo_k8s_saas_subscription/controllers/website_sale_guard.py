"""
controllers/website_sale_guard.py

Defense-in-depth: redirect unauthenticated users to the login page when
their cart contains SaaS subscription products.  The native Odoo config
(account_on_checkout = mandatory) handles the normal flow, but this guard
catches edge cases such as direct URL access.
"""
import logging
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

logger = logging.getLogger(__name__)


class WebsiteSaleSaaSGuard(WebsiteSale):

    @http.route()
    def checkout(self, **post):
        """Redirect to login if user is public and cart contains SaaS products."""
        if request.env.user._is_public():
            order = request.website.sale_get_order()
            if order and self._cart_has_saas(order):
                logger.info(
                    "Blocking guest checkout for order %s — SaaS products in cart",
                    order.name,
                )
                return request.redirect("/web/login?redirect=/shop/checkout")

        return super().checkout(**post)

    def _cart_has_saas(self, order):
        """Return True if any order line is a SaaS subscription product."""
        saas_categ = request.env.ref(
            "odoo_k8s_saas.product_category_odoo_saas", raise_if_not_found=False
        )
        for line in order.order_line:
            if not line.product_id:
                continue
            if saas_categ:
                categ = line.product_id.categ_id
                while categ:
                    if categ.id == saas_categ.id:
                        return True
                    categ = categ.parent_id
            if "saas" in (line.product_id.name or "").lower():
                return True
        return False
