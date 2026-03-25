/**
 * Cart warning toast — vanilla JS, no Odoo module imports.
 *
 * Intercepts XMLHttpRequest responses to /shop/cart/update_json;
 * if the JSON body contains a "warning" key, display a Bootstrap 5 toast.
 */
(function () {
    "use strict";

    var _origOpen = XMLHttpRequest.prototype.open;
    var _origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url) {
        this._saasUrl = url;
        return _origOpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function () {
        var xhr = this;
        if (xhr._saasUrl && xhr._saasUrl.indexOf("/shop/cart/update") !== -1) {
            xhr.addEventListener("load", function () {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data && data.warning) {
                        _showToast(data.warning);
                    }
                } catch (e) {
                    // Not JSON or parse error — ignore
                }
            });
        }
        return _origSend.apply(this, arguments);
    };

    function _showToast(message) {
        var id = "saas-cart-warn-" + Date.now();
        var html =
            '<div id="' + id + '" ' +
            'class="toast align-items-center text-bg-warning border-0 position-fixed bottom-0 end-0 m-3" ' +
            'role="alert" aria-live="assertive" aria-atomic="true" ' +
            'data-bs-delay="8000" style="z-index:10000;">' +
            '<div class="d-flex">' +
            '<div class="toast-body fw-semibold">' +
            '<i class="fa fa-exclamation-triangle me-1"></i> ' +
            message +
            '</div>' +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto" ' +
            'data-bs-dismiss="toast" aria-label="Close"></button>' +
            '</div></div>';
        document.body.insertAdjacentHTML("beforeend", html);
        var el = document.getElementById(id);
        if (el && window.bootstrap && window.bootstrap.Toast) {
            var toast = new window.bootstrap.Toast(el);
            toast.show();
            el.addEventListener("hidden.bs.toast", function () { el.remove(); });
        }
    }
})();
