{
    'name': 'Odoo K8s SaaS — Subscription Bridge',
    'version': '18.0.1.0.0',
    'summary': 'Links subscription_oca lifecycle to SaaS instance provisioning',
    'category': 'Technical',
    'author': 'AEI Software',
    'license': 'LGPL-3',
    'depends': ['odoo_k8s_saas', 'subscription_oca'],
    'data': [
        'security/ir.model.access.csv',
        'data/subscription_templates.xml',
        'views/saas_instance_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
