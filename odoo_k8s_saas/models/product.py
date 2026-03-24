from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    odoo_version = fields.Selection([
        ('17.0', 'Odoo 17.0 (Official)'),
        ('18.0', 'Odoo 18.0 (Official)'),
        ('19.0', 'Odoo 19.0 (Official)'),
        ('custom', 'Custom Image'),
    ], string="Odoo Version", default='18.0',
       help="Select the Odoo version to provision when this product is sold.")

    custom_image = fields.Char(string="Custom Odoo Image",
                               help="e.g. ghcr.io/my-org/my-odoo:18.0. Only used if Odoo Version is Custom.")
