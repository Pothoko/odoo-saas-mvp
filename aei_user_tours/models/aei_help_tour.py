import json
import logging
import re
import unicodedata

import requests

from odoo import api, fields, models
from odoo.tools import ormcache

_logger = logging.getLogger(__name__)

_LLM_TIMEOUT_S = 5


def _normalize(text):
    """lowercase + sin tildes + colapsa espacios. Para matching."""
    if not text:
        return ''
    nfkd = unicodedata.normalize('NFKD', text)
    no_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', no_accents.lower()).strip()


class AeiHelpTour(models.Model):
    _name = 'aei.help.tour'
    _description = 'Tour interactivo del Centro de Ayuda'
    _order = 'sequence, id'

    name = fields.Char(string='Título', required=True, translate=True)
    tour_name = fields.Char(
        string='Identificador JS',
        required=True,
        help='Nombre del tour registrado en registry.category("web_tour.tours")',
    )
    description = fields.Text(string='Descripción', translate=True)
    icon = fields.Char(
        string='Ícono',
        default='fa-play-circle',
        help='Clase FontAwesome, ej. fa-rocket, fa-cog, fa-users',
    )
    category = fields.Selection(
        [
            ('admin', 'Administración'),
            ('sales', 'Ventas'),
            ('billing', 'Facturación / Pagos'),
            ('tenant', 'Portal del cliente'),
            ('shop', 'Tienda / Compra'),
            ('general', 'General'),
        ],
        string='Categoría',
        default='general',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    duration_min = fields.Integer(
        string='Duración (min)',
        default=2,
        help='Estimación informativa para el usuario',
    )
    keywords = fields.Char(
        string='Palabras clave',
        help='Separadas por coma. Ej: comprar, compra, pagar, QR',
    )
    intent_phrases = fields.Text(
        string='Frases de ejemplo',
        help='Una por línea. Ej: "cómo hago una compra"',
    )
    target = fields.Selection(
        [('backend', 'Backend (admin)'), ('frontend', 'Tienda pública')],
        string='Contexto',
        default='backend',
        help='Dónde se ejecuta el tour. Cambia la URL a la que se redirige.',
    )
    landing_url = fields.Char(
        string='URL inicial',
        help='URL a la que se navega antes de iniciar el tour (ej. /shop, /odoo/saas)',
    )

    def action_launch_tour(self):
        """Acción cliente que dispara el tour en el navegador."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'aei_user_tours.launch',
            'params': {
                'tour_name': self.tour_name,
                'title': self.name,
                'landing_url': self.landing_url or '',
            },
        }

    # ─────────────────────────── Intent matching ───────────────────────────
    # Diseñado para reemplazarse por un LLM más adelante: sobrescribe
    # _match_score() y la API pública sigue funcionando igual.

    @api.model
    def search_intent(self, query, limit=5):
        """Punto de entrada del asistente conversacional.

        Recibe la pregunta del usuario en lenguaje natural y devuelve los
        tours más relevantes, ya rankeados. Pensado para llamarse vía RPC
        desde el widget flotante.

        Estrategia:
          1. Heurística local por keywords/frases (siempre corre, ~0ms).
          2. Si `aei_user_tours.llm_provider` está configurado y el top
             score heurístico es bajo (ambigüedad), pide rerank al LLM.
        """
        query_norm = _normalize(query)
        if not query_norm:
            return []
        tours = self.search([('active', '=', True)])
        scored = []
        for tour in tours:
            score = tour._match_score(query_norm)
            if score > 0:
                scored.append((score, tour))
        scored.sort(key=lambda t: t[0], reverse=True)

        top_score = scored[0][0] if scored else 0
        provider = self.env['ir.config_parameter'].sudo().get_param(
            'aei_user_tours.llm_provider', ''
        ).strip().lower()
        # LLM se usa cuando: 1) está configurado, 2) la heurística no es
        # claramente concluyente (≤ 8 = match débil de palabras sueltas, no
        # de keyword explícita que pesa 10).
        if provider and top_score <= 8 and tours:
            try:
                # tuple() porque ormcache requiere args hasheables
                llm_ids = self._llm_rerank(query_norm, tuple(sorted(tours.ids)))
                if llm_ids:
                    by_id = {t.id: t for t in tours}
                    scored = [
                        ((1000 - i), by_id[tid])
                        for i, tid in enumerate(llm_ids)
                        if tid in by_id
                    ]
            except Exception as e:
                _logger.warning("AEI LLM rerank falló (%s) — usando heurística", e)

        results = []
        for score, tour in scored[:limit]:
            results.append({
                'id': tour.id,
                'name': tour.name,
                'description': tour.description or '',
                'icon': tour.icon or 'fa-play-circle',
                'tour_name': tour.tour_name,
                'landing_url': tour.landing_url or '',
                'target': tour.target,
                'score': score,
            })
        return results

    # ─────────────────────────── LLM rerank (opt-in) ───────────────────────
    # Activado por config parameters:
    #   aei_user_tours.llm_provider     ej. "moonshot"  (vacío = off)
    #   aei_user_tours.llm_api_key      Bearer token
    #   aei_user_tours.llm_base_url     default https://api.moonshot.ai/v1
    #   aei_user_tours.llm_model        default moonshot-v1-8k
    # Costo aprox. Moonshot/Kimi: <0.001 USD por consulta (prompt corto).

    @ormcache('query_norm', 'tour_ids')
    def _llm_rerank(self, query_norm, tour_ids):
        """Devuelve los IDs de tour ordenados según el LLM.

        `tour_ids` debe ser tuple (hasheable). Se cachea por (query, catálogo)
        durante la vida del worker; tras `write()` sobre cualquier aei.help.tour,
        Odoo invalida el cache automáticamente vía clear_caches.
        """
        param = self.env['ir.config_parameter'].sudo().get_param
        api_key = param('aei_user_tours.llm_api_key', '')
        if not api_key:
            return []
        base_url = param('aei_user_tours.llm_base_url', '').strip() or \
            'https://api.moonshot.ai/v1'
        model = param('aei_user_tours.llm_model', '').strip() or 'moonshot-v1-8k'

        tours = self.browse(tour_ids)
        catalog = [
            {
                'id': t.id,
                'name': t.name,
                'description': (t.description or '')[:200],
                'keywords': t.keywords or '',
            }
            for t in tours
        ]
        system_prompt = (
            "Eres el clasificador de intent del asistente AEI. Dada la pregunta "
            "del usuario y un catálogo de guías, devuelve un JSON {\"ids\": [...]} "
            "con los IDs de las guías más relevantes, en orden descendente. "
            "Si ninguna aplica, devuelve {\"ids\": []}. NO escribas nada más."
        )
        user_prompt = json.dumps({'query': query_norm, 'catalog': catalog}, ensure_ascii=False)

        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt},
                ],
                'temperature': 0.0,
                'max_tokens': 256,
                'response_format': {'type': 'json_object'},
            },
            timeout=_LLM_TIMEOUT_S,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        parsed = json.loads(content)
        ids = parsed.get('ids') or []
        # Filtrar a IDs conocidos (defensa contra alucinaciones).
        valid = [i for i in ids if isinstance(i, int) and i in set(tour_ids)]
        return valid

    def _match_score(self, query_norm):
        """Heurística simple por keywords + frases. Override para LLM."""
        self.ensure_one()
        score = 0
        # 1) keywords explícitas (peso alto)
        for kw in (self.keywords or '').split(','):
            kw_norm = _normalize(kw)
            if kw_norm and kw_norm in query_norm:
                score += 10
        # 2) frases de ejemplo (similitud por palabras compartidas)
        query_words = set(query_norm.split())
        for phrase in (self.intent_phrases or '').splitlines():
            phrase_norm = _normalize(phrase)
            if not phrase_norm:
                continue
            phrase_words = set(phrase_norm.split())
            if not phrase_words:
                continue
            overlap = len(phrase_words & query_words)
            if overlap:
                score += overlap * 2
        # 3) match en título/descripción (peso bajo)
        for field_val in (self.name, self.description):
            if field_val and any(w in _normalize(field_val) for w in query_words if len(w) > 3):
                score += 1
        return score

    @api.model
    def get_all_for_help_center(self):
        """Listado liviano de tours activos para el widget del asistente."""
        tours = self.search([('active', '=', True)])
        return [
            {
                'id': t.id,
                'name': t.name,
                'description': t.description or '',
                'icon': t.icon or 'fa-play-circle',
                'tour_name': t.tour_name,
                'category': t.category,
                'landing_url': t.landing_url or '',
                'target': t.target,
            }
            for t in tours
        ]
