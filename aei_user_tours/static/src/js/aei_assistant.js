/** @odoo-module **/

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

/**
 * AEI Assistant — botoncito flotante con chat.
 *
 * El usuario hace clic en el botón "AEI" y se abre un panel donde
 * puede preguntar en lenguaje natural (ej. "¿cómo hago una compra?").
 * El asistente busca el tour más relevante y ofrece guiarlo paso a paso.
 */
export class AeiAssistant extends Component {
    static template = "aei_user_tours.AeiAssistant";
    static props = {};

    setup() {
        this.action = useService("action");
        this.inputRef = useRef("input");
        this.state = useState({
            open: false,
            query: "",
            loading: false,
            messages: [
                {
                    role: "bot",
                    text: "¡Hola! Soy AEI. ¿En qué te ayudo? Por ejemplo: «¿cómo hago una compra?»",
                },
            ],
            suggestions: [],
        });

        onMounted(() => {
            // Sugerir tours iniciales al abrir por primera vez
            this._loadInitialSuggestions();
        });
    }

    async _loadInitialSuggestions() {
        try {
            const tours = await rpc("/web/dataset/call_kw", {
                model: "aei.help.tour",
                method: "get_all_for_help_center",
                args: [],
                kwargs: {},
            });
            this.state.suggestions = tours.slice(0, 3);
        } catch (e) {
            // silencioso: si falla, simplemente no hay sugerencias iniciales
            console.warn("AEI: no se pudieron cargar sugerencias", e);
        }
    }

    toggle() {
        this.state.open = !this.state.open;
        if (this.state.open) {
            // foco en el input al abrir
            setTimeout(() => this.inputRef.el?.focus(), 50);
        }
    }

    async onSubmit(ev) {
        ev?.preventDefault?.();
        const query = (this.state.query || "").trim();
        if (!query || this.state.loading) return;
        this.state.messages.push({ role: "user", text: query });
        this.state.query = "";
        this.state.loading = true;
        try {
            const results = await rpc("/web/dataset/call_kw", {
                model: "aei.help.tour",
                method: "search_intent",
                args: [query],
                kwargs: { limit: 3 },
            });
            if (!results || !results.length) {
                this.state.messages.push({
                    role: "bot",
                    text: "No encontré una guía exacta. Te muestro todos los tours disponibles para que elijas uno.",
                    suggestions: this.state.suggestions,
                });
            } else {
                const top = results[0];
                this.state.messages.push({
                    role: "bot",
                    text: `Encontré esta guía: «${top.name}». ¿Quieres que te lleve paso a paso?`,
                    suggestions: results,
                });
            }
        } catch (e) {
            console.error("AEI: error al buscar intent", e);
            this.state.messages.push({
                role: "bot",
                text: "Ups, tuve un problema buscando esa guía. Intenta de nuevo.",
            });
        } finally {
            this.state.loading = false;
            // scroll al final
            setTimeout(() => {
                const list = document.querySelector(".o_aei_messages");
                if (list) list.scrollTop = list.scrollHeight;
            }, 30);
        }
    }

    async launchTour(suggestion) {
        this.state.open = false;
        await this.action.doAction({
            type: "ir.actions.client",
            tag: "aei_user_tours.launch",
            params: {
                tour_name: suggestion.tour_name,
                title: suggestion.name,
                landing_url: suggestion.landing_url || "",
                target: suggestion.target || "backend",
            },
        });
    }
}

registry.category("main_components").add("aei_user_tours.AeiAssistant", {
    Component: AeiAssistant,
});
