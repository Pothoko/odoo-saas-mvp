/** @odoo-module **/

import { WebsiteSale } from "@website_sale/js/website_sale";
import { patch } from "@web/core/utils/patch";

/*
 * Intercept the cart update response; if the back-end attached a `warning`
 * key (SaaS duplicate-plan message), display it as a Bootstrap 5 toast.
 */
patch(WebsiteSale.prototype, {
    /**
     * @override
     */
    async _onClickAdd(ev) {
        const result = await this._super(...arguments);
        this._showCartWarning(result);
        return result;
    },

    _showCartWarning(result) {
        if (!result || !result.warning) {
            return;
        }

        // Build a Bootstrap 5 toast element
        const toastId = `saas-cart-warn-${Date.now()}`;
        const html = `
            <div id="${toastId}"
                 class="toast align-items-center text-bg-warning border-0 position-fixed bottom-0 end-0 m-3"
                 role="alert" aria-live="assertive" aria-atomic="true"
                 data-bs-delay="8000" style="z-index:10000;">
                <div class="d-flex">
                    <div class="toast-body fw-semibold">
                        <i class="fa fa-exclamation-triangle me-1"></i>
                        ${result.warning}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto"
                            data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML("beforeend", html);
        const toastEl = document.getElementById(toastId);
        if (toastEl && window.bootstrap) {
            const toast = new window.bootstrap.Toast(toastEl);
            toast.show();
            // Cleanup DOM after the toast hides
            toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
        }
    },
});
