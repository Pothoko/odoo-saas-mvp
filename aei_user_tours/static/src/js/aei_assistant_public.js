/**
 * AEI Assistant — frontend público (vanilla JS, sin Owl).
 *
 * Se monta en cualquier página de website (/shop, /shop/cart, /shop/checkout,
 * /payment/qr_mercantil/display, etc.) y conversa con el visitante:
 *
 *   - Botón flotante "AEI" abajo-derecha.
 *   - Panel chat: el usuario escribe "como hago una compra".
 *   - Llama a /aei/help/intent (auth='public') y muestra tarjetas con tours.
 *   - Al hacer clic en "Guíame", arranca el tour de web_tour (si está cargado
 *     en assets_frontend) o redirige al landing_url y guarda el tour pendiente
 *     en sessionStorage para que tour_launcher.js lo reanude.
 *
 * No depende de Owl ni de los servicios del backend porque éstos no están
 * disponibles en las plantillas QWeb públicas de website.
 */
(function () {
    "use strict";

    const PENDING_KEY = "aei_pending_tour";
    const FAB_ID = "o_aei_fab_public";
    const PANEL_ID = "o_aei_panel_public";

    // Evita doble inyección si el script se incluye dos veces.
    if (window.__aeiAssistantPublicMounted) return;
    window.__aeiAssistantPublicMounted = true;

    function h(tag, attrs = {}, children = []) {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs)) {
            if (k === "class") el.className = v;
            else if (k === "style") el.style.cssText = v;
            else if (k.startsWith("on") && typeof v === "function") {
                el.addEventListener(k.slice(2).toLowerCase(), v);
            } else if (v != null) {
                el.setAttribute(k, v);
            }
        }
        for (const child of [].concat(children)) {
            if (child == null) continue;
            el.appendChild(
                typeof child === "string" ? document.createTextNode(child) : child
            );
        }
        return el;
    }

    async function rpc(url, params) {
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error.data?.message || data.error.message);
        return data.result;
    }

    function _startTour(tourName) {
        // Primero intenta el overlay visual propio (cursor flotante).
        if (window.AEIGuide && (window.AEI_GUIDES || {})[tourName]) {
            window.AEIGuide.start(tourName);
            return true;
        }
        // Fallback: web_tour (sólo si nuestro overlay no está cargado).
        const svc = window.odoo?.__WOWL_DEBUG__?.root?.env?.services?.tour_service;
        if (svc?.startTour) {
            svc.startTour(tourName, { mode: "manual" });
            return true;
        }
        if (window.odoo?.startTour) {
            window.odoo.startTour(tourName);
            return true;
        }
        console.warn("AEI: no se pudo iniciar el tour", tourName);
        return false;
    }

    function launchTour(suggestion) {
        // Si nuestro overlay ya conoce el tour, lo arranca acá mismo —
        // el motor maneja la navegación entre páginas por sí solo vía
        // `url` en cada paso + sessionStorage.
        if (window.AEIGuide && (window.AEI_GUIDES || {})[suggestion.tour_name]) {
            setTimeout(() => _startTour(suggestion.tour_name), 150);
            return;
        }
        // Fallback antiguo (web_tour): redirige al landing_url si es necesario.
        const sameOrigin =
            !suggestion.landing_url ||
            window.location.pathname.startsWith(suggestion.landing_url);
        if (suggestion.landing_url && !sameOrigin) {
            sessionStorage.setItem(
                PENDING_KEY,
                JSON.stringify({ tour_name: suggestion.tour_name, ts: Date.now() })
            );
            window.location.href = suggestion.landing_url;
            return;
        }
        setTimeout(() => _startTour(suggestion.tour_name), 200);
    }

    // ── UI ──────────────────────────────────────────────────────────────────

    let suggestionsCache = null;

    function buildCard(sug) {
        return h(
            "div",
            {
                class: "o_aei_card",
                onclick: () => launchTour(sug),
            },
            [
                h("i", { class: `fa ${sug.icon || "fa-play-circle"} me-2` }),
                h("div", { class: "o_aei_card_body" }, [
                    h("div", { class: "o_aei_card_title" }, sug.name),
                    sug.description
                        ? h("div", { class: "o_aei_card_desc" }, sug.description)
                        : null,
                ]),
                h(
                    "button",
                    {
                        class: "btn btn-sm btn-primary",
                        type: "button",
                        onclick: (ev) => {
                            ev.stopPropagation();
                            launchTour(sug);
                        },
                    },
                    [h("i", { class: "fa fa-play me-1" }), " Guíame"]
                ),
            ]
        );
    }

    function appendMessage(messagesEl, role, text, suggestions) {
        const wrap = h("div", { class: `o_aei_msg o_aei_msg_${role}` }, [
            h("div", { class: "o_aei_msg_bubble" }, text),
        ]);
        if (suggestions && suggestions.length) {
            const list = h("div", { class: "o_aei_suggestions" });
            suggestions.forEach((s) => list.appendChild(buildCard(s)));
            wrap.appendChild(list);
        }
        messagesEl.appendChild(wrap);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    async function loadInitialSuggestions() {
        if (suggestionsCache) return suggestionsCache;
        try {
            const res = await rpc("/aei/help/list", {});
            suggestionsCache = res?.tours || [];
        } catch (e) {
            console.warn("AEI: no se pudieron cargar tours", e);
            suggestionsCache = [];
        }
        return suggestionsCache;
    }

    async function handleSubmit(input, messagesEl) {
        const q = (input.value || "").trim();
        if (!q) return;
        input.value = "";
        appendMessage(messagesEl, "user", q);

        const typing = h("div", { class: "o_aei_msg o_aei_msg_bot" }, [
            h("div", { class: "o_aei_msg_bubble o_aei_typing" }, [
                h("span"),
                h("span"),
                h("span"),
            ]),
        ]);
        messagesEl.appendChild(typing);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        try {
            const res = await rpc("/aei/help/intent", { query: q, limit: 3 });
            typing.remove();
            const results = res?.results || [];
            if (!results.length) {
                const all = await loadInitialSuggestions();
                appendMessage(
                    messagesEl,
                    "bot",
                    "No encontré una guía exacta. Te muestro todas las que tengo para que elijas.",
                    all.slice(0, 4)
                );
            } else {
                const top = results[0];
                appendMessage(
                    messagesEl,
                    "bot",
                    `Encontré esta guía: «${top.name}». ¿La activamos?`,
                    results
                );
            }
        } catch (e) {
            console.error("AEI: error al buscar intent", e);
            typing.remove();
            appendMessage(
                messagesEl,
                "bot",
                "Ups, tuve un problema. Intenta de nuevo en un momento."
            );
        }
    }

    function buildPanel() {
        const messagesEl = h("div", { class: "o_aei_messages" });
        const input = h("input", {
            type: "text",
            class: "form-control o_aei_input",
            placeholder: "Pregúntame: ¿cómo hago una compra?",
            autocomplete: "off",
        });
        const submitBtn = h(
            "button",
            { type: "submit", class: "btn btn-primary" },
            [h("i", { class: "fa fa-paper-plane" })]
        );
        const form = h(
            "form",
            {
                class: "o_aei_input_row",
                onsubmit: (ev) => {
                    ev.preventDefault();
                    handleSubmit(input, messagesEl);
                },
            },
            [input, submitBtn]
        );

        const closeBtn = h(
            "button",
            {
                class: "o_aei_close",
                type: "button",
                title: "Cerrar",
                onclick: () => togglePanel(false),
            },
            [h("i", { class: "fa fa-times" })]
        );

        const panel = h(
            "div",
            { id: PANEL_ID, class: "o_aei_panel", style: "display:none" },
            [
                h("div", { class: "o_aei_header" }, [
                    h("div", { class: "o_aei_header_title" }, [
                        h("strong", {}, "AEI"),
                        " ",
                        h("span", { class: "o_aei_header_sub" }, "Tu asistente"),
                    ]),
                    closeBtn,
                ]),
                messagesEl,
                form,
            ]
        );

        // Mensaje inicial + sugerencias top 3
        appendMessage(
            messagesEl,
            "bot",
            "¡Hola! Soy AEI. ¿En qué te ayudo? Por ejemplo: «¿cómo hago una compra?»"
        );
        loadInitialSuggestions().then((tours) => {
            if (tours.length) {
                appendMessage(
                    messagesEl,
                    "bot",
                    "Estas son algunas guías rápidas:",
                    tours.slice(0, 3)
                );
            }
        });

        panel._input = input;
        return panel;
    }

    function togglePanel(forceOpen) {
        const panel = document.getElementById(PANEL_ID);
        const fab = document.getElementById(FAB_ID);
        if (!panel || !fab) return;
        const willOpen =
            typeof forceOpen === "boolean"
                ? forceOpen
                : panel.style.display === "none";
        panel.style.display = willOpen ? "flex" : "none";
        fab.innerHTML = willOpen
            ? '<i class="fa fa-times"></i>'
            : '<span class="o_aei_fab_label">AEI</span>';
        if (willOpen) {
            setTimeout(() => panel._input?.focus(), 50);
        }
    }

    function mount() {
        // No mostrar si ya existe el assistant Owl (backend embebido en iframe, etc.)
        if (document.querySelector(".o_aei_assistant .o_aei_fab")) return;
        // No mostrar dentro de un tour activo de web_tour (para no taparlo).
        if (document.body.classList.contains("o_tour_running")) return;

        const fab = h(
            "button",
            {
                id: FAB_ID,
                class: "o_aei_fab",
                type: "button",
                title: "Pregúntale a AEI",
                onclick: () => togglePanel(),
            },
            [h("span", { class: "o_aei_fab_label" }, "AEI")]
        );

        const root = h(
            "div",
            { class: "o_aei_assistant o_aei_assistant_public" },
            [fab]
        );
        document.body.appendChild(root);
        // Panel se inyecta al lado del FAB la primera vez que se abre — para
        // evitar montar el form/textarea hasta que el usuario lo pida (perf).
        let panelMounted = false;
        fab.addEventListener(
            "click",
            () => {
                if (panelMounted) return;
                panelMounted = true;
                root.appendChild(buildPanel());
                // togglePanel ya se llamó por el onclick; pero aún no existía el panel.
                // Forzar abierto:
                togglePanel(true);
            },
            { once: true }
        );
    }

    function tryResumePending() {
        let pending;
        try {
            pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null");
        } catch (e) {
            pending = null;
        }
        if (!pending?.tour_name) return;
        sessionStorage.removeItem(PENDING_KEY);
        setTimeout(() => _startTour(pending.tour_name), 800);
    }

    function init() {
        mount();
        tryResumePending();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
