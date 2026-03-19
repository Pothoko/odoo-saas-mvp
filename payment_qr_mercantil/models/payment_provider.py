import logging
import requests
from datetime import datetime, timedelta

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = 'https://sip.mc4.com.bo:8443'


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('qr_mercantil', 'QR Mercantil')],
        ondelete={'qr_mercantil': 'set default'},
    )

    # ── Credentials ─────────────────────────────────────────────────────────
    qr_mercantil_api_key = fields.Char(
        string='API Key (Login)',
        help='Header "apikey" para el endpoint de autenticación.',
        required_if_provider='qr_mercantil',
    )
    qr_mercantil_api_key_service = fields.Char(
        string='API Key Servicio',
        help='Header "apikeyServicio" para los endpoints de QR.',
        required_if_provider='qr_mercantil',
    )
    qr_mercantil_username = fields.Char(
        string='Usuario API',
        required_if_provider='qr_mercantil',
    )
    qr_mercantil_password = fields.Char(
        string='Contraseña API',
        required_if_provider='qr_mercantil',
    )
    qr_mercantil_base_url = fields.Char(
        string='URL Base API',
        default=_DEFAULT_BASE_URL,
        required_if_provider='qr_mercantil',
    )

    # ── API helpers ──────────────────────────────────────────────────────────

    def _qr_mercantil_get_token(self):
        """Obtiene un JWT token del endpoint de autenticación."""
        self.ensure_one()
        url = f"{self.qr_mercantil_base_url}/autenticacion/v1/generarToken"
        try:
            resp = requests.post(
                url,
                headers={
                    'apikey': self.qr_mercantil_api_key,
                    'Content-Type': 'application/json',
                },
                json={
                    'username': self.qr_mercantil_username,
                    'password': self.qr_mercantil_password,
                },
                timeout=15,
                verify=True,
            )
            resp.raise_for_status()
            data = resp.json()
            # Handle {"token":"..."} or raw JWT string
            if isinstance(data, dict):
                return (
                    data.get('token')
                    or data.get('accessToken')
                    or data.get('access_token')
                    or ''
                )
            return str(data)
        except requests.exceptions.RequestException as exc:
            _logger.error("QR Mercantil: error al obtener token: %s", exc)
            raise ValidationError(
                _("No se pudo autenticar con QR Mercantil: %s") % exc
            )

    def _qr_mercantil_generate_qr(
        self, alias, amount, currency_name, description, callback_url, due_date=None
    ):
        """Genera un QR en el banco y retorna el payload de respuesta."""
        self.ensure_one()
        token = self._qr_mercantil_get_token()
        if not due_date:
            due_date = (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y')

        url = f"{self.qr_mercantil_base_url}/api/v1/generaQr"
        try:
            resp = requests.post(
                url,
                headers={
                    'apikeyServicio': self.qr_mercantil_api_key_service,
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                },
                json={
                    'alias': alias,
                    'callback': callback_url,
                    'detalleGlosa': description,
                    'monto': float(amount),
                    'moneda': currency_name,
                    'fechaVencimiento': due_date,
                    'tipoSolicitud': 'API',
                },
                timeout=15,
                verify=True,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            _logger.error("QR Mercantil: error al generar QR (alias=%s): %s", alias, exc)
            raise ValidationError(
                _("No se pudo generar el QR Mercantil: %s") % exc
            )

    def _qr_mercantil_get_status(self, alias):
        """Consulta el estado de una transacción por alias."""
        self.ensure_one()
        token = self._qr_mercantil_get_token()
        url = f"{self.qr_mercantil_base_url}/api/v1/estadoTransaccion"
        try:
            resp = requests.post(
                url,
                headers={
                    'apikeyServicio': self.qr_mercantil_api_key_service,
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                },
                json={'alias': alias},
                timeout=15,
                verify=True,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            _logger.error("QR Mercantil: error al consultar estado (alias=%s): %s", alias, exc)
            return {}

    # ── Odoo payment flow ────────────────────────────────────────────────────

    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.code != 'qr_mercantil':
            return res

        reference = processing_values.get('reference', '')
        amount = processing_values.get('amount', 0)
        currency = processing_values.get('currency')
        currency_name = currency.name if currency else 'BOB'

        base_url = (
            self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        )
        callback_url = f"{base_url}/payment/qr_mercantil/webhook"

        qr_image = ''
        qr_id = ''
        try:
            qr_data = self._qr_mercantil_generate_qr(
                alias=reference,
                amount=amount,
                currency_name=currency_name,
                description=f"Pedido {reference}",
                callback_url=callback_url,
            )
            # Try common field names the bank may use
            qr_image = (
                qr_data.get('qrImage')
                or qr_data.get('imagenQr')
                or qr_data.get('qr_image')
                or qr_data.get('image')
                or ''
            )
            qr_id = (
                qr_data.get('idQr')
                or qr_data.get('id_qr')
                or qr_data.get('id')
                or ''
            )
        except Exception:
            _logger.exception(
                "QR Mercantil: fallo al generar QR para referencia %s", reference
            )

        # Persist on the matching transaction
        tx = self.env['payment.transaction'].sudo().search(
            [('reference', '=', reference)], limit=1
        )
        if tx:
            tx.write({
                'qr_mercantil_alias': reference,
                'qr_mercantil_image': qr_image,
                'qr_mercantil_qr_id': qr_id,
            })

        return {
            'qr_image': qr_image,
            'qr_id': qr_id,
            'alias': reference,
            'amount': amount,
            'currency': currency_name,
            'status_url': f"{base_url}/payment/qr_mercantil/status",
            'landing_route': processing_values.get('landing_route', '/payment/status'),
        }
