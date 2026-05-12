/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Tour: ¿Cómo hago una compra?
 *
 * Cubre: navegar tienda → elegir plan → agregar al carrito → checkout
 * → seleccionar pago QR. Los selectores son los estándar de Odoo eCommerce
 * (website_sale).
 */
registry.category("web_tour.tours").add("aei_tour_shop_purchase", {
    url: "/shop",
    steps: () => [
        {
            trigger: "#products_grid, .oe_product, .o_wsale_products_grid_table_wrapper",
            content: "Esta es la tienda. Aquí ves los planes disponibles.",
            tooltipPosition: "bottom",
            run: () => {},
        },
        {
            trigger: ".oe_product_cart a, .oe_product a.oe_product_image_link",
            content: "Haz clic en el plan que quieres contratar.",
            tooltipPosition: "right",
            run: "click",
        },
        {
            trigger: "#add_to_cart, a#add_to_cart",
            content: "Pulsa «Agregar al carrito».",
            tooltipPosition: "right",
            run: "click",
        },
        {
            trigger: "a[href='/shop/cart'], .o_wsale_my_cart, a:contains('Proceed to Checkout'), a:contains('Continuar')",
            content: "Ahora vamos al carrito para revisar tu pedido.",
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            trigger: "a[href*='/shop/checkout'], a.btn-primary:contains('Checkout'), a.btn-primary:contains('Finalizar')",
            content: "Avanza al checkout para completar tus datos.",
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            trigger: "input[name='name'], input[name='email']",
            content: "Completa tus datos personales. Los campos obligatorios están marcados.",
            tooltipPosition: "right",
            run: () => {},
        },
        {
            trigger: "input[name='o_payment_radio'][data-provider-code='qr_mercantil'], label:contains('QR'), input[type='radio'][name*='payment']",
            content: "Elige «Pago con QR» (Banco Mercantil) como método de pago.",
            tooltipPosition: "right",
            run: "click",
        },
        {
            trigger: "button[name='o_payment_submit_button'], button:contains('Pay'), button:contains('Pagar')",
            content: "Haz clic en «Pagar». Te mostraremos el QR para escanear con tu app del banco.",
            tooltipPosition: "top",
            run: () => {},
        },
    ],
});
