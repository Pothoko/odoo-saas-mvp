"""
models/saas_instance.py

Extends saas.instance with a link to sale.subscription.
"""
from odoo import models, fields


class SaasInstance(models.Model):
    _inherit = "saas.instance"

    subscription_id = fields.Many2one(
        "sale.subscription",
        string="Subscription",
        ondelete="set null",
        tracking=True,
        help="Recurring subscription that manages billing for this instance.",
    )
    subscription_stage = fields.Char(
        string="Subscription Stage",
        related="subscription_id.stage_id.name",
        readonly=True,
    )
