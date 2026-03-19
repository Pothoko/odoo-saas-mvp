import logging
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Known "paid" states from MC4 / Bolivian bank APIs
_PAID_STATES = frozenset({
    'PAGADO', 'PAGADA', 'EJECUTADO', 'EJECUTADA',
    'APROBADO', 'APROBADA', 'COMPLETADO', 'COMPLETADA',
    'PROCESADO', 'PROCESADA', 'DONE', 'PAID', 'SUCCESS',
})


class QRMercantilController(http.Controller):

    # ── Redirect target — shown after "Pagar ahora" is clicked ───────────────

    @http.route(
        '/payment/qr_mercantil/display',
        type='http',
        auth='public',
        website=True,
        methods=['GET'],
        sitemap=False,
    )
    def display_qr(self, reference=None, **kwargs):
        """Show the QR code page and start polling for payment confirmation."""
        if not reference:
            return request.redirect('/payment/status')

        tx = request.env['payment.transaction'].sudo().search(
            [('reference', '=', reference), ('provider_code', '=', 'qr_mercantil')],
            limit=1,
        )
        if not tx:
            _logger.warning("QR Mercantil: transaction not found for reference=%s", reference)
            return request.redirect('/payment/status')

        return request.render('payment_qr_mercantil.qr_mercantil_display', {
            'reference': reference,
            'qr_image': tx.qr_mercantil_image or '',
            'amount': tx.amount,
            'currency': tx.currency_id.name if tx.currency_id else 'BOB',
            'landing_route': tx.landing_route or '/payment/status',
        })

    # ── Webhook — called by the bank when QR is paid (best-effort) ───────────

    @http.route(
        '/payment/qr_mercantil/webhook',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def webhook(self, **kwargs):
        """Receive payment notification from Banco Mercantil (best-effort)."""
        notification_data = request.get_json_data()
        _logger.info("QR Mercantil webhook recibido: %s", notification_data)

        try:
            request.env['payment.transaction'].sudo()._handle_notification_data(
                'qr_mercantil', notification_data
            )
        except Exception:
            _logger.exception("QR Mercantil: error procesando webhook")
            return {'status': 'error', 'message': 'processing error'}

        return {'status': 'ok'}

    # ── Status polling — called by frontend JS every ~3 seconds ──────────────

    # Throttle: query bank at most once every N seconds per reference
    _bank_poll_last: dict = {}
    BANK_POLL_INTERVAL = 10  # seconds

    @http.route(
        '/payment/qr_mercantil/status',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def check_status(self, reference=None, **kwargs):
        """Return Odoo tx state; poll bank API every 10 s as webhook fallback."""
        if not reference:
            return {'state': 'error', 'message': 'missing reference'}

        tx = request.env['payment.transaction'].sudo().search(
            [('reference', '=', reference), ('provider_code', '=', 'qr_mercantil')],
            limit=1,
        )
        if not tx:
            return {'state': 'error', 'message': 'transaction not found'}

        # Short-circuit: already in a terminal state
        if tx.state in ('done', 'cancel', 'error'):
            return {
                'state': tx.state,
                'reference': tx.reference,
                'landing_route': tx.landing_route or '/payment/status',
            }

        # ── Webhook fallback: poll bank's estadoTransaccion ───────────────────
        now = time.time()
        last_poll = self._bank_poll_last.get(reference, 0)
        if now - last_poll >= self.BANK_POLL_INTERVAL:
            self._bank_poll_last[reference] = now
            alias = tx.qr_mercantil_alias or reference
            try:
                status_data = tx.provider_id._qr_mercantil_get_status(alias)
                _logger.info(
                    "QR Mercantil: polling estado banco ref=%s alias=%s → %s",
                    reference, alias, status_data,
                )

                # MC4 wraps data inside 'objeto'
                objeto = status_data.get('objeto') or {}
                estado = (
                    objeto.get('estado')
                    or objeto.get('estadoTransaccion')
                    or objeto.get('status')
                    or status_data.get('estado')
                    or ''
                ).upper()

                is_paid = (
                    estado in _PAID_STATES
                    or objeto.get('pagado') is True
                    or objeto.get('paid') is True
                )

                if is_paid:
                    _logger.info(
                        "QR Mercantil: pago confirmado vía polling → ref=%s estado=%s",
                        reference, estado,
                    )
                    notification_data = {
                        'alias': alias,
                        'monto': objeto.get('monto') or tx.amount,
                        'idQr': objeto.get('idQr') or tx.qr_mercantil_qr_id or '',
                    }
                    tx._handle_notification_data('qr_mercantil', notification_data)

            except Exception:
                _logger.exception(
                    "QR Mercantil: error al consultar estado banco ref=%s", reference
                )

        # Re-read after possible state change
        tx.invalidate_recordset()
        return {
            'state': tx.state,
            'reference': tx.reference,
            'landing_route': tx.landing_route or '/payment/status',
        }
