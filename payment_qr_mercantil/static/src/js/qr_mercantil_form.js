/** @odoo-module **/
/**
 * QR Mercantil — frontend polling
 * Checks tx state every 3s and redirects on success/failure.
 */

import { browser } from "@web/core/browser/browser";

const POLL_INTERVAL_MS = 3000;

function startQRPolling() {
    const refInput = document.getElementById("qr_mercantil_reference");
    const statusUrlInput = document.getElementById("qr_mercantil_status_url");
    const landingInput = document.getElementById("qr_mercantil_landing");
    const msgEl = document.getElementById("qr_mercantil_status_msg");

    if (!refInput || !statusUrlInput) return; // Not on QR Mercantil form

    const reference = refInput.value;
    const statusUrl = statusUrlInput.value;
    const landingRoute = (landingInput && landingInput.value) || "/payment/status";

    if (!reference || !statusUrl) return;

    let attempts = 0;
    const MAX_ATTEMPTS = 200; // 200 × 3s = 10 minutes timeout

    const intervalId = setInterval(async () => {
        attempts++;
        if (attempts > MAX_ATTEMPTS) {
            clearInterval(intervalId);
            if (msgEl) {
                msgEl.innerHTML =
                    '<span class="text-warning">⚠️ Tiempo de espera agotado. Si ya pagaste, el pedido se confirmará automáticamente.</span>';
            }
            return;
        }

        try {
            const resp = await fetch(statusUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { reference } }),
            });
            const data = await resp.json();
            const state = (data.result || {}).state;

            if (state === "done") {
                clearInterval(intervalId);
                if (msgEl) {
                    msgEl.innerHTML =
                        '<span class="text-success">✅ ¡Pago confirmado! Redirigiendo…</span>';
                }
                browser.setTimeout(() => {
                    window.location.href = landingRoute;
                }, 1500);
            } else if (state === "cancel" || state === "error") {
                clearInterval(intervalId);
                if (msgEl) {
                    msgEl.innerHTML =
                        '<span class="text-danger">❌ Pago cancelado o fallido.</span>';
                }
            }
        } catch (e) {
            // Network error — keep polling silently
            console.debug("QR Mercantil poll error:", e);
        }
    }, POLL_INTERVAL_MS);
}

// Start when DOM is ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startQRPolling);
} else {
    startQRPolling();
}
