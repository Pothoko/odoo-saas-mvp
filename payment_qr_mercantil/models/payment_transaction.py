import logging

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    qr_mercantil_alias = fields.Char(string='QR Alias')
    qr_mercantil_image = fields.Text(string='QR Image (base64)')
    qr_mercantil_qr_id = fields.Char(string='QR ID Banco')

    # ── Find transaction from webhook ────────────────────────────────────────

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'qr_mercantil' or len(tx) == 1:
            return tx

        alias = notification_data.get('alias')
        if not alias:
            raise ValidationError(
                _("QR Mercantil webhook: campo 'alias' ausente en la notificación.")
            )

        tx = self.search([
            ('qr_mercantil_alias', '=', alias),
            ('provider_code', '=', 'qr_mercantil'),
        ])
        if not tx:
            raise ValidationError(
                _("QR Mercantil: no se encontró transacción con alias '%s'.") % alias
            )
        return tx

    # ── Process webhook payload ──────────────────────────────────────────────

    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != 'qr_mercantil':
            return

        # Webhook payload fields from the bank:
        # alias, numeroOrdenOriginante, monto, idQr,
        # moneda, fechaProceso, cuentaCliente, nombreCliente, documentoClient
        monto = notification_data.get('monto')
        id_qr = notification_data.get('idQr', '')
        nombre_cliente = notification_data.get('nombreCliente', '')

        _logger.info(
            "QR Mercantil: webhook recibido para tx=%s alias=%s monto=%s idQr=%s cliente=%s",
            self.reference,
            self.qr_mercantil_alias,
            monto,
            id_qr,
            nombre_cliente,
        )

        # Save bank QR ID if not already stored
        if id_qr and not self.qr_mercantil_qr_id:
            self.qr_mercantil_qr_id = id_qr

        # Confirm the payment — bank only calls webhook on successful payment
        self._set_done()
        _logger.info(
            "QR Mercantil: transacción %s marcada como DONE", self.reference
        )
