{
    'name': 'Odoo K8s SaaS',
    'version': '18.0.1.0.0',
    'summary': 'SaaS management addon: provision and manage tenants via the SaaS portal API',
    'category': 'Technical',
    'author': 'AEI Software',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/saas_instance_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
