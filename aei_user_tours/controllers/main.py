import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AeiHelpPublic(http.Controller):
    """Public endpoints that power the AEI Assistant widget on the website.

    These run sudo() because we want anonymous visitors on /shop to be able
    to ask "¿cómo compro?" without logging in. The data exposed (tour name,
    title, description, icon, landing URL) is intentionally non-sensitive —
    it is the same content shown to admins in the Help Center backend view.
    """

    def _serialize_tour(self, tour):
        return {
            'id': tour.id,
            'name': tour.name,
            'description': tour.description or '',
            'icon': tour.icon or 'fa-play-circle',
            'tour_name': tour.tour_name,
            'category': tour.category,
            'landing_url': tour.landing_url or '',
            'target': tour.target,
            'duration_min': tour.duration_min,
        }

    @http.route(
        '/aei/help/list',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def list_tours(self, **kwargs):
        tours = request.env['aei.help.tour'].sudo().search([('active', '=', True)])
        return {
            'tours': [self._serialize_tour(t) for t in tours],
        }

    @http.route(
        '/aei/help/intent',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def intent(self, query=None, limit=5, **kwargs):
        if not query or not isinstance(query, str):
            return {'results': []}
        # search_intent is cheap (in-memory heuristic). LLM rerank, if
        # enabled, also lives behind this RPC.
        results = request.env['aei.help.tour'].sudo().search_intent(query, limit=limit)
        return {'results': results, 'query': query}
