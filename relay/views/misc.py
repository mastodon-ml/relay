import aputils
import subprocess

from aiohttp.web import Request
from pathlib import Path

from .base import View, register_route

from .. import __version__
from ..misc import Response


VERSION = __version__


if Path(__file__).parent.parent.joinpath('.git').exists():
	try:
		commit_label = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode('ascii')
		VERSION = f'{__version__} {commit_label}'

	except Exception:
		pass


@register_route('/nodeinfo/{niversion:\\d.\\d}.json', '/nodeinfo/{niversion:\\d.\\d}')
class NodeinfoView(View):
	async def get(self, request: Request, niversion: str) -> Response:
		with self.database.session() as conn:
			inboxes = conn.get_inboxes()

			nodeinfo = aputils.Nodeinfo.new(
				name = 'activityrelay',
				version = VERSION,
				protocols = ['activitypub'],
				open_regs = not conn.get_config('whitelist-enabled'),
				users = 1,
				repo = 'https://git.pleroma.social/pleroma/relay' if niversion == '2.1' else None,
				metadata = {
					'approval_required': conn.get_config('approval-required'),
					'peers': [inbox['domain'] for inbox in inboxes]
				}
			)

		return Response.new(nodeinfo, ctype = 'json')


@register_route('/.well-known/nodeinfo')
class WellknownNodeinfoView(View):
	async def get(self, request: Request) -> Response:
		data = aputils.WellKnownNodeinfo.new_template(self.config.domain)

		return Response.new(data, ctype = 'json')
