{
    'name': 'AEI User Tours',
    'version': '18.0.1.0.0',
    'summary': 'Guías interactivas paso a paso para usuarios (Help Center)',
    'description': """
Centro de Ayuda con tours interactivos para usuarios finales.
Resalta elementos en pantalla y guía al usuario paso a paso usando el
framework nativo web_tour de Odoo.
""",
    'category': 'Tools',
    'author': 'AEI Software',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'web_tour', 'odoo_k8s_saas'],
    'data': [
        'security/ir.model.access.csv',
        'data/aei_help_tour_data.xml',
        'views/aei_help_tour_views.xml',
    ],
    'assets': {
        # Backend: widget AEI completo + overlay visual + datos de tours.
        # web_tour queda como fallback histórico para tours legacy.
        'web.assets_backend': [
            'aei_user_tours/static/src/scss/aei_assistant.scss',
            'aei_user_tours/static/src/scss/aei_guide_overlay.scss',
            'aei_user_tours/static/src/js/aei_guide_overlay.js',
            'aei_user_tours/static/src/js/aei_guides_data.js',
            'aei_user_tours/static/src/js/aei_assistant.js',
            'aei_user_tours/static/src/xml/aei_assistant.xml',
            'aei_user_tours/static/src/js/tour_launcher.js',
            'aei_user_tours/static/src/js/tours/saas_first_instance_tour.js',
            'aei_user_tours/static/src/js/tours/shop_purchase_tour.js',
            'aei_user_tours/static/src/js/tours/qr_payment_tour.js',
        ],
        # Frontend (website público: /shop, /shop/cart, /shop/checkout,
        # /payment/qr_mercantil/display…): widget AEI vanilla-JS + overlay
        # visual con cursor flotante. NO incluye web_tour porque en el
        # frontend público el motor de web_tour no se inicia limpiamente.
        'web.assets_frontend': [
            'aei_user_tours/static/src/scss/aei_assistant.scss',
            'aei_user_tours/static/src/scss/aei_guide_overlay.scss',
            'aei_user_tours/static/src/js/aei_guide_overlay.js',
            'aei_user_tours/static/src/js/aei_guides_data.js',
            'aei_user_tours/static/src/js/aei_assistant_public.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
