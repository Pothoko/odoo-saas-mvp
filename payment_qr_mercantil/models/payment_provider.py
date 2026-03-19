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
    qr_mercantil_webhook_url = fields.Char(
        string='Webhook URL (Callback)',
        help=(
            'URL que el banco llamará cuando se complete un pago QR. '
            'Se envía como campo "callback" en cada llamada a generaQr. '
            'Ejemplo: https://admin.aeisoftware.com/payment/qr_mercantil/webhook\n'
            'Si se deja vacío se usa el dominio configurado en Ajustes → Parámetros técnicos → web.base.url'
        ),
    )

    # ── Odoo 18 payment method declaration ──────────────────────────────────

    def _get_payment_method_information(self):
        res = super()._get_payment_method_information()
        res['qr_mercantil'] = {'mode': 'unique', 'domain': [('type', '=', 'unknown')]}
        return res

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

    # ── Odoo 18 payment flow ─────────────────────────────────────────────────
    # NOTE: _get_specific_rendering_values is defined on PaymentTransaction
    #       (see payment_transaction.py) — Odoo 18 calls it on the TX model.
