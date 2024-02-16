from __future__ import annotations

import typing

from .base import View, register_route

from ..misc import Response

if typing.TYPE_CHECKING:
	from aiohttp.web import Request


HOME_TEMPLATE = """
	<html><head>
	<title>ActivityPub Relay at {host}</title>
	<style>
	p {{ color: #FFFFFF; font-family: monospace, arial; font-size: 100%; }}
	body {{ background-color: #000000; }}
	a {{ color: #26F; }}
	a:visited {{ color: #46C; }}
	a:hover {{ color: #8AF; }}
	</style>
	</head>
	<body>
	<p>This is an Activity Relay for fediverse instances.</p>
	<p>{note}</p>
	<p>
		You may subscribe to this relay with the address:
		<a href="https://{host}/actor">https://{host}/actor</a>
	</p>
	<p>
		To host your own relay, you may download the code at this address:
		<a href="https://git.pleroma.social/pleroma/relay">
			https://git.pleroma.social/pleroma/relay
		</a>
	</p>
	<br><p>List of {count} registered instances:<br>{targets}</p>
	</body></html>
"""


# pylint: disable=unused-argument

@register_route('/')
class HomeView(View):
	async def get(self, request: Request) -> Response:
		with self.database.connection(False) as conn:
			config = conn.get_config_all()
			inboxes = conn.execute('SELECT * FROM inboxes').all()

		text = HOME_TEMPLATE.format(
			host = self.config.domain,
			note = config['note'],
			count = len(inboxes),
			targets = '<br>'.join(inbox['domain'] for inbox in inboxes)
		)

		return Response.new(text, ctype='html')
