from __future__ import annotations

import asyncio
import subprocess
import traceback
import typing

from aputils.errors import SignatureFailureError
from aputils.misc import Digest, HttpDate, Signature
from aputils.objects import Nodeinfo, Webfinger, WellKnownNodeinfo
from pathlib import Path

from . import __version__
from . import logger as logging
from .misc import Message, Response, View
from .processors import run_processor

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from aputils.signer import Signer
	from collections.abc import Callable


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


# pylint: disable=unused-argument

@register_route('/')
class HomeView(View):
	async def get(self, request: Request) -> Response:
		with self.database.connection() as conn:
			config = conn.get_config_all()
			inboxes = conn.execute('SELECT * FROM inboxes').all()

			text = HOME_TEMPLATE.format(
				host = self.config.domain,
				note = config['note'],
				count = len(inboxes),
				targets = '<br>'.join(inbox['domain'] for inbox in inboxes)
			)

		return Response.new(text, ctype='html')



@register_route('/actor', '/inbox')
class ActorView(View):
	def __init__(self, request: Request):
		View.__init__(self, request)

		self.signature: Signature = None
		self.message: Message = None
		self.actor: Message = None
		self.instance: dict[str, str] = None
		self.signer: Signer = None


	async def get(self, request: Request) -> Response:
		data = Message.new_actor(
			host = self.config.domain,
			pubkey = self.app.signer.pubkey
		)

		return Response.new(data, ctype='activity')


	async def post(self, request: Request) -> Response:
		if (response := await self.get_post_data()):
			return response

		with self.database.connection() as conn:
			self.instance = conn.get_inbox(self.actor.inbox)
			config = conn.get_config_all()

			## reject if the actor isn't whitelisted while the whiltelist is enabled
			if config['whitelist-enabled'] and not conn.get_domain_whitelist(self.actor.domain):
				logging.verbose('Rejected actor for not being in the whitelist: %s', self.actor.id)
				return Response.new_error(403, 'access denied', 'json')

			## reject if actor is banned
			if conn.get_domain_ban(self.actor.domain):
				logging.verbose('Ignored request from banned actor: %s', self.actor.id)
				return Response.new_error(403, 'access denied', 'json')

			## reject if activity type isn't 'Follow' and the actor isn't following
			if self.message.type != 'Follow' and not self.instance:
				logging.verbose(
					'Rejected actor for trying to post while not following: %s',
					self.actor.id
				)

				return Response.new_error(401, 'access denied', 'json')

			logging.debug('>> payload %s', self.message.to_json(4))

			asyncio.ensure_future(run_processor(self))
			return Response.new(status = 202)


	async def get_post_data(self) -> Response | None:
		try:
			self.signature = Signature.new_from_signature(self.request.headers['signature'])

		except KeyError:
			logging.verbose('Missing signature header')
			return Response.new_error(400, 'missing signature header', 'json')

		try:
			self.message = await self.request.json(loads = Message.parse)

		except Exception:
			traceback.print_exc()
			logging.verbose('Failed to parse inbox message')
			return Response.new_error(400, 'failed to parse message', 'json')

		if self.message is None:
			logging.verbose('empty message')
			return Response.new_error(400, 'missing message', 'json')

		if 'actor' not in self.message:
			logging.verbose('actor not in message')
			return Response.new_error(400, 'no actor in message', 'json')

		self.actor = await self.client.get(self.signature.keyid, sign_headers = True)

		if self.actor is None:
			# ld signatures aren't handled atm, so just ignore it
			if self.message.type == 'Delete':
				logging.verbose('Instance sent a delete which cannot be handled')
				return Response.new(status=202)

			logging.verbose(f'Failed to fetch actor: {self.signature.keyid}')
			return Response.new_error(400, 'failed to fetch actor', 'json')

		try:
			self.signer = self.actor.signer

		except KeyError:
			logging.verbose('Actor missing public key: %s', self.signature.keyid)
			return Response.new_error(400, 'actor missing public key', 'json')

		try:
			self.validate_signature(await self.request.read())

		except SignatureFailureError as e:
			logging.verbose('signature validation failed for "%s": %s', self.actor.id, e)
			return Response.new_error(401, str(e), 'json')


	def validate_signature(self, body: bytes) -> None:
		headers = {key.lower(): value for key, value in self.request.headers.items()}
		headers["(request-target)"] = " ".join([self.request.method.lower(), self.request.path])

		if (digest := Digest.new_from_digest(headers.get("digest"))):
			if not body:
				raise SignatureFailureError("Missing body for digest verification")

			if not digest.validate(body):
				raise SignatureFailureError("Body digest does not match")

		if self.signature.algorithm_type == "hs2019":
			if "(created)" not in self.signature.headers:
				raise SignatureFailureError("'(created)' header not used")

			current_timestamp = HttpDate.new_utc().timestamp()

			if self.signature.created > current_timestamp:
				raise SignatureFailureError("Creation date after current date")

			if current_timestamp > self.signature.expires:
				raise SignatureFailureError("Expiration date before current date")

			headers["(created)"] = self.signature.created
			headers["(expires)"] = self.signature.expires

		# pylint: disable=protected-access
		if not self.signer._validate_signature(headers, self.signature):
			raise SignatureFailureError("Signature does not match")


@register_route('/.well-known/webfinger')
class WebfingerView(View):
	async def get(self, request: Request) -> Response:
		try:
			subject = request.query['resource']

		except KeyError:
			return Response.new_error(400, 'missing "resource" query key', 'json')

		if subject != f'acct:relay@{self.config.domain}':
			return Response.new_error(404, 'user not found', 'json')

		data = Webfinger.new(
			handle = 'relay',
			domain = self.config.domain,
			actor = self.config.actor
		)

		return Response.new(data, ctype = 'json')


@register_route('/nodeinfo/{niversion:\\d.\\d}.json', '/nodeinfo/{niversion:\\d.\\d}')
class NodeinfoView(View):
	async def get(self, request: Request, niversion: str) -> Response:
		with self.database.connection() as conn:
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
