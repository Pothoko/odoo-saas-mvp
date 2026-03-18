"""
models/sale_order.py

Deprecated: Subscriptions and SaaS instances are now managed 
exclusively via sale_subscription.py stage transitions, 
triggering instance creation upon 'In Progress'.
"""
from odoo import models

class SaleOrder(models.Model):
    _inherit = "sale.order"
