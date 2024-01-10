from __future__ import annotations

import aputils
import asyncio
import subprocess
import traceback
import typing

from aputils.objects import Nodeinfo, Webfinger, WellKnownNodeinfo
from pathlib import Path

from . import __version__, misc
from . import logger as logging
from .misc import Message, Response, View
from .processors import run_processor

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from typing import Callable


VIEWS = []
VERSION = __version__
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
	<p>You may subscribe to this relay with the address: <a href="https://{host}/actor">https://{host}/actor</a></p>
	<p>To host your own relay, you may download the code at this address: <a href="https://git.pleroma.social/pleroma/relay">https://git.pleroma.social/pleroma/relay</a></p>
	<br><p>List of {count} registered instances:<br>{targets}</p>
	</body></html>
"""


if Path(__file__).parent.parent.joinpath('.git').exists():
	try:
		commit_label = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode('ascii')
		VERSION = f'{__version__} {commit_label}'

	except Exception:
		pass


def register_route(*paths: str) -> Callable:
	def wrapper(view: View) -> View:
		for path in paths:
			VIEWS.append([path, view])

		return View
	return wrapper


@register_route('/')
class HomeView(View):
	async def get(self, request: Request) -> Response:
		text = HOME_TEMPLATE.format(
			host = self.config.host,
			note = self.config.note,
			count = len(self.database.hostnames),
			targets = '<br>'.join(self.database.hostnames)
		)

		return Response.new(text, ctype='html')



@register_route('/actor', '/inbox')
class ActorView(View):
	async def get(self, request: Request) -> Response:
		data = Message.new_actor(
			host = self.config.host, 
			pubkey = self.database.signer.pubkey
		)

		return Response.new(data, ctype='activity')


	async def post(self, request: Request) -> Response:
		response = await self.get_post_data()

		if response is not None:
			return response

		## reject if the actor isn't whitelisted while the whiltelist is enabled
		if self.config.whitelist_enabled and not self.config.is_whitelisted(self.actor.domain):
			logging.verbose('Rejected actor for not being in the whitelist: %s', self.actor.id)
			return Response.new_error(403, 'access denied', 'json')

		## reject if actor is banned
		if self.config.is_banned(self.actor.domain):
			logging.verbose('Ignored request from banned actor: %s', self.actor.id)
			return Response.new_error(403, 'access denied', 'json')

		## reject if activity type isn't 'Follow' and the actor isn't following
		if self.message.type != 'Follow' and not self.database.get_inbox(self.actor.domain):
			logging.verbose(
				'Rejected actor for trying to post while not following: %s',
				self.actor.id
			)

			return Response.new_error(401, 'access denied', 'json')

		logging.debug('>> payload %s', self.message.to_json(4))

		asyncio.ensure_future(run_processor(self))
		return Response.new(status = 202)


@register_route('/.well-known/webfinger')
class WebfingerView(View):
	async def get(self, request: Request) -> Response:
		try:
			subject = request.query['resource']

		except KeyError:
			return Response.new_error(400, 'missing "resource" query key', 'json')

		if subject != f'acct:relay@{self.config.host}':
			return Response.new_error(404, 'user not found', 'json')

		data = Webfinger.new(
			handle = 'relay',
			domain = self.config.host,
			actor = self.config.actor
		)

		return Response.new(data, ctype = 'json')


@register_route('/nodeinfo/{niversion:\\d.\\d}.json', '/nodeinfo/{niversion:\\d.\\d}')
class NodeinfoView(View):
	async def get(self, request: Request, niversion: str) -> Response:
		data = dict(
			name = 'activityrelay',
			version = VERSION,
			protocols = ['activitypub'],
			open_regs = not self.config.whitelist_enabled,
			users = 1,
			metadata = {'peers': self.database.hostnames}
		)

		if niversion == '2.1':
			data['repo'] = 'https://git.pleroma.social/pleroma/relay'

		return Response.new(Nodeinfo.new(**data), ctype = 'json')


@register_route('/.well-known/nodeinfo')
class WellknownNodeinfoView(View):
	async def get(self, request: Request) -> Response:
		data = WellKnownNodeinfo.new_template(self.config.host)
		return Response.new(data, ctype = 'json')
