/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("aei_tour_saas_first_instance", {
    url: "/odoo/action-odoo_k8s_saas.action_saas_instances",
    steps: () => [
        {
            trigger: ".o_control_panel",
            content: "Estás en el panel de instancias SaaS. Desde aquí gestionas todos los tenants.",
            tooltipPosition: "bottom",
            run: () => {},
        },
        {
            trigger: ".o_list_button_add, .o-kanban-button-new",
            content: "Haz clic en «Nuevo» para crear una instancia.",
            tooltipPosition: "bottom",
            run: "click",
        },
        {
            trigger: "input[name='name'], .o_field_widget[name='name'] input",
            content: "Escribe el nombre comercial del cliente.",
            tooltipPosition: "right",
            run: "edit Mi Primera Empresa",
        },
        {
            trigger: "input[name='tenant_id'], .o_field_widget[name='tenant_id'] input",
            content: "El tenant_id se usa como subdominio. Solo minúsculas, números y guiones.",
            tooltipPosition: "right",
            run: "edit mi-primera-empresa",
        },
        {
            trigger: ".o_field_widget[name='plan']",
            content: "Elige el plan: Starter, Pro o Enterprise.",
            tooltipPosition: "right",
            run: () => {},
        },
        {
            trigger: "button[name='action_provision']",
            content: "Cuando todo esté listo, haz clic en «Provision» para crear la instancia en Kubernetes.",
            tooltipPosition: "bottom",
            run: () => {},
        },
    ],
});
