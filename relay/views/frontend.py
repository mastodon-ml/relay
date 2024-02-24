from __future__ import annotations

import typing

from .base import View, register_route

from ..misc import Response

if typing.TYPE_CHECKING:
	from aiohttp.web import Request


# pylint: disable=unused-argument

@register_route('/')
class HomeView(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			instances = tuple(conn.execute('SELECT * FROM inboxes').all())

		# text = HOME_TEMPLATE.format(
		# 	host = self.config.domain,
		# 	note = config['note'],
		# 	count = len(inboxes),
		# 	targets = '<br>'.join(inbox['domain'] for inbox in inboxes)
		# )

		data = self.template.render('page/home.haml', instances = instances)
		return Response.new(data, ctype='html')


@register_route('/style.css')
class StyleCss(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('style.css')
		return Response.new(data, ctype = 'css')
