/**
 * AEI Guides — definición de pasos para los tours visuales.
 *
 * Cada paso es { trigger, content, action, position, url, scroll }.
 *   - trigger: CSS selector (acepta lista separada por coma y `:contains("...")`)
 *   - content: texto del globo de diálogo
 *   - action:  "click" (espera que el usuario haga click en el target)
 *              | "info" (sólo informativo, avanza con "Siguiente")
 *   - position: "top" | "bottom" | "left" | "right" (auto si se omite)
 *   - url: navega a esa URL antes de mostrar el paso (suspende el tour, persiste
 *          el resto en sessionStorage, y se reanuda automáticamente).
 *
 * Indexado por `tour_name` (el mismo string que vive en aei.help.tour.tour_name).
 */
(function () {
    "use strict";

    window.AEI_GUIDES = window.AEI_GUIDES || {};

    // ────────────────────────────────────────────────────────────────────────
    // Cómo hacer una compra (frontend público /shop → /checkout → /payment)
    // ────────────────────────────────────────────────────────────────────────
    window.AEI_GUIDES.aei_tour_shop_purchase = {
        title: "Cómo hago una compra",
        steps: [
            {
                content:
                    "¡Te voy a guiar paso a paso! Empezamos en la tienda — ahora te muestro qué hacer.",
                action: "info",
                url: "/shop",
            },
            {
                trigger:
                    ".oe_product_cart, article.oe_product, .o_wsale_product_grid_wrapper article, .oe_product",
                content: "Hacé click en cualquiera de estos planes para verlo en detalle.",
                action: "click",
                position: "bottom",
            },
            {
                trigger:
                    "#add_to_cart, a#add_to_cart, button[name='add_to_cart'], a:contains('Agregar al carrito'), button:contains('Agregar al carrito')",
                content: "Ahora dale a «Agregar al carrito».",
                action: "click",
                position: "left",
            },
            {
                trigger:
                    "a[href='/shop/cart'], a[href*='/shop/cart'], .o_wsale_my_cart, a:contains('Ver el carrito'), a:contains('carrito')",
                content: "Vamos a revisar tu carrito antes de pagar.",
                action: "click",
                position: "bottom",
            },
            {
                trigger:
                    "a[href*='/shop/checkout'], a.btn-primary[href*='checkout'], a:contains('Finalizar'), a:contains('Continuar'), a:contains('Checkout')",
                content: "Dale a «Continuar al pago» para ir al checkout.",
                action: "click",
                position: "top",
            },
            {
                trigger: "input[name='name']",
                content: "Empezamos con tus datos. Acá va tu nombre completo.",
                action: "info",
                position: "right",
            },
            {
                trigger: "input[name='email']",
                content: "Tu email — te llegará la confirmación de la compra acá.",
                action: "info",
                position: "right",
            },
            {
                trigger: "input[name='phone']",
                content: "Tu teléfono de contacto.",
                action: "info",
                position: "right",
            },
            {
                trigger: "input[name='company_name']",
                content: "El nombre de tu empresa (este será el nombre fiscal de la factura).",
                action: "info",
                position: "right",
            },
            {
                trigger: "input[name='vat']",
                content: "Tu NIT/RUC para la facturación.",
                action: "info",
                position: "right",
            },
            {
                trigger:
                    "button[type='submit'], a.btn-primary[href*='confirm'], a.btn-primary[href*='next'], button:contains('Confirmar'), button:contains('Siguiente'), button:contains('Continuar')",
                content: "Cuando todo esté completo, dale a Confirmar para pasar al pago.",
                action: "click",
                position: "top",
            },
            {
                trigger:
                    "input[type='radio'][data-provider-code='qr_mercantil'], input[name='o_payment_radio'][data-provider-code='qr_mercantil'], label:contains('QR'), input[type='radio'][name*='payment']",
                content: "Elegí «Pago con QR Mercantil» como método de pago.",
                action: "click",
                position: "right",
            },
            {
                trigger:
                    "button[name='o_payment_submit_button'], button:contains('Pagar'), button:contains('Pay')",
                content: "Y dale a «Pagar ahora». Te vamos a mostrar el código QR para escanear con tu app del banco.",
                action: "click",
                position: "top",
            },
        ],
    };

    // ────────────────────────────────────────────────────────────────────────
    // Pagar con código QR (sólo si ya estás en la pantalla del QR)
    // ────────────────────────────────────────────────────────────────────────
    window.AEI_GUIDES.aei_tour_qr_payment = {
        title: "Pagar con QR (Mercantil)",
        steps: [
            {
                content:
                    "Para pagar con QR primero tenés que llegar a la pantalla de pago. Si todavía no la ves, hacé «Cómo hago una compra» primero.",
                action: "info",
            },
            {
                trigger:
                    "img.o_qr_mercantil_image, img[src*='qr'], .o_qr_payment_image, .qr-code img",
                content:
                    "Este es el código QR. Abrí la app de tu banco, elegí «Pagar con QR» y escaneá esta imagen.",
                action: "info",
                position: "right",
            },
            {
                trigger:
                    ".o_qr_status, .o_payment_status, .alert-info, #qr_mercantil_status_msg",
                content:
                    "Cuando confirmes el pago en tu app, esta pantalla se actualiza sola en pocos segundos.",
                action: "info",
                position: "top",
            },
        ],
    };

    // ────────────────────────────────────────────────────────────────────────
    // Crear primera instancia SaaS (backend admin)
    // ────────────────────────────────────────────────────────────────────────
    window.AEI_GUIDES.aei_tour_saas_first_instance = {
        title: "Crear tu primera instancia SaaS",
        steps: [
            {
                content:
                    "Te llevo al panel de instancias SaaS. Desde ahí gestionás todos los tenants Odoo en Kubernetes.",
                action: "info",
                url: "/odoo/action-odoo_k8s_saas.action_saas_instances",
            },
            {
                trigger:
                    ".o_list_button_add, .o-kanban-button-new, button:contains('Nuevo'), button:contains('New')",
                content: "Dale a «Nuevo» para crear una instancia.",
                action: "click",
                position: "bottom",
            },
            {
                trigger:
                    "input[name='name'], .o_field_widget[name='name'] input",
                content: "Escribí el nombre comercial del cliente.",
                action: "info",
                position: "right",
            },
            {
                trigger:
                    "input[name='tenant_id'], .o_field_widget[name='tenant_id'] input",
                content:
                    "El tenant_id se usa como subdominio. Sólo minúsculas, números y guiones (ej. acme-corp).",
                action: "info",
                position: "right",
            },
            {
                trigger: ".o_field_widget[name='plan']",
                content: "Elegí el plan: Starter, Pro o Enterprise.",
                action: "info",
                position: "right",
            },
            {
                trigger: "button[name='action_provision']",
                content: "Cuando todo esté listo, hacé click en «Provision» para crear la instancia en Kubernetes.",
                action: "click",
                position: "bottom",
            },
        ],
    };
})();
