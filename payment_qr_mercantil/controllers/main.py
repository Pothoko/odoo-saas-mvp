import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


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

    # ── Webhook — called by the bank when QR is paid ─────────────────────────

    @http.route(
        '/payment/qr_mercantil/webhook',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def webhook(self, **kwargs):
        """Receive payment notification from Banco Mercantil Santa Cruz."""
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

    # ── Status polling — called by frontend JS every few seconds ─────────────

    @http.route(
        '/payment/qr_mercantil/status',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def check_status(self, reference=None, **kwargs):
        """Return current Odoo tx state for frontend polling."""
        if not reference:
            return {'state': 'error', 'message': 'missing reference'}

        tx = request.env['payment.transaction'].sudo().search(
            [('reference', '=', reference), ('provider_code', '=', 'qr_mercantil')],
            limit=1,
        )
        if not tx:
            return {'state': 'error', 'message': 'transaction not found'}

        return {
            'state': tx.state,              # draft | pending | authorized | done | cancel | error
            'reference': tx.reference,
            'landing_route': tx.landing_route or '/payment/status',
        }
