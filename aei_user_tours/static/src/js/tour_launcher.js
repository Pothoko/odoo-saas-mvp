/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Client action que arranca un tour de web_tour por su nombre.
 *
 * Se invoca con:
 *   { type: "ir.actions.client",
 *     tag: "aei_user_tours.launch",
 *     params: { tour_name, title, landing_url, target } }
 *
 * Si el tour es frontend (tienda pública) o tiene landing_url distinta
 * a la actual, redirige antes de arrancar y guarda el tour pendiente en
 * sessionStorage. El arranque se reanuda en el siguiente load.
 */

const PENDING_KEY = "aei_pending_tour";

function _startTour(tourName) {
    const tourService = odoo?.__WOWL_DEBUG__?.root?.env?.services?.tour_service;
    if (tourService?.startTour) {
        tourService.startTour(tourName, { mode: "manual" });
        return true;
    }
    // Fallback: API histórica
    if (window.odoo?.startTour) {
        window.odoo.startTour(tourName);
        return true;
    }
    return false;
}

function tryResumePending() {
    let pending;
    try {
        pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null");
    } catch (e) {
        pending = null;
    }
    if (!pending?.tour_name) return;
    // Limpiar antes de intentar, así si falla no quedamos en loop
    sessionStorage.removeItem(PENDING_KEY);
    // Pequeño delay para que la página termine de montar
    setTimeout(() => _startTour(pending.tour_name), 600);
}

// Al cargar el módulo, ver si veníamos de una redirección
if (typeof window !== "undefined") {
    if (document.readyState === "complete" || document.readyState === "interactive") {
        tryResumePending();
    } else {
        document.addEventListener("DOMContentLoaded", tryResumePending);
    }
}

registry.category("actions").add("aei_user_tours.launch", async (env, action) => {
    const { tour_name, landing_url, target } = action.params || {};
    if (!tour_name) {
        return;
    }
    const needsRedirect =
        landing_url &&
        (target === "frontend" || !window.location.pathname.startsWith(landing_url));

    if (needsRedirect) {
        sessionStorage.setItem(
            PENDING_KEY,
            JSON.stringify({ tour_name, ts: Date.now() })
        );
        window.location.href = landing_url;
        return;
    }
    _startTour(tour_name);
});
