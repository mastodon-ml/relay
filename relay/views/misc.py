from __future__ import annotations

import subprocess
import typing

from aputils.objects import Nodeinfo, WellKnownNodeinfo
from pathlib import Path

from .base import View, register_route

from .. import __version__
from ..misc import Response

if typing.TYPE_CHECKING:
	from aiohttp.web import Request


VERSION = __version__


if Path(__file__).parent.parent.joinpath('.git').exists():
	try:
		commit_label = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode('ascii')
		VERSION = f'{__version__} {commit_label}'

	except Exception:
		pass


# pylint: disable=unused-argument

@register_route('/nodeinfo/{niversion:\\d.\\d}.json', '/nodeinfo/{niversion:\\d.\\d}')
class NodeinfoView(View):
	# pylint: disable=no-self-use
	async def get(self, request: Request, niversion: str) -> Response:
		with self.database.session() as conn:
			inboxes = conn.execute('SELECT * FROM inboxes').all()

			data = {
				'name': 'activityrelay',
				'version': VERSION,
				'protocols': ['activitypub'],
				'open_regs': not conn.get_config('whitelist-enabled'),
				'users': 1,
				'metadata': {'peers': [inbox['domain'] for inbox in inboxes]}
			}

		if niversion == '2.1':
			data['repo'] = 'https://git.pleroma.social/pleroma/relay'

		return Response.new(Nodeinfo.new(**data), ctype = 'json')


@register_route('/.well-known/nodeinfo')
class WellknownNodeinfoView(View):
	async def get(self, request: Request) -> Response:
		data = WellKnownNodeinfo.new_template(self.config.domain)

		return Response.new(data, ctype = 'json')
