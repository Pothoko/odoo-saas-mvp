/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Tour: pagar con QR (Banco Mercantil).
 *
 * Pensado para arrancar en cualquier página: si el usuario aún no está
 * en la pantalla de QR, el primer paso le dice qué hacer; si ya está,
 * resalta el QR y la confirmación.
 */
registry.category("web_tour.tours").add("aei_tour_qr_payment", {
    steps: () => [
        {
            trigger: "body",
            content: "Para pagar con QR, primero elige un plan en la tienda y avanza al checkout. Cuando veas el código QR, vuelve a abrirme.",
            tooltipPosition: "top",
            run: () => {},
        },
        {
            trigger: "img.o_qr_mercantil_image, img[src*='qr'], .o_qr_payment_image",
            content: "Escanea este QR con la app de tu banco. El monto y referencia ya vienen incluidos.",
            tooltipPosition: "right",
            run: () => {},
        },
        {
            trigger: ".o_qr_status, .o_payment_status, .alert-info",
            content: "Cuando completes el pago en tu app, esta pantalla se actualiza sola en pocos segundos.",
            tooltipPosition: "top",
            run: () => {},
        },
    ],
});
