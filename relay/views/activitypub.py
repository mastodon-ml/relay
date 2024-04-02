from __future__ import annotations

import aputils
import traceback
import typing

from .base import View, register_route

from .. import logger as logging
from ..misc import Message, Response
from ..processors import run_processor

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from bsql import Row


@register_route('/actor', '/inbox')
class ActorView(View):
	signature: aputils.Signature
	message: Message
	actor: Message
	instancce: Row
	signer: aputils.Signer


	def __init__(self, request: Request):
		View.__init__(self, request)


	async def get(self, request: Request) -> Response:
		with self.database.session(False) as conn:
			config = conn.get_config_all()

		data = Message.new_actor(
			host = self.config.domain,
			pubkey = self.app.signer.pubkey,
			description = self.app.template.render_markdown(config.note),
			approves = config.approval_required
		)

		return Response.new(data, ctype='activity')


	async def post(self, request: Request) -> Response:
		if response := await self.get_post_data():
			return response

		with self.database.session() as conn:
			self.instance = conn.get_inbox(self.actor.shared_inbox)

			# reject if actor is banned
			if conn.get_domain_ban(self.actor.domain):
				logging.verbose('Ignored request from banned actor: %s', self.actor.id)
				return Response.new_error(403, 'access denied', 'json')

			# reject if activity type isn't 'Follow' and the actor isn't following
			if self.message.type != 'Follow' and not self.instance:
				logging.verbose(
					'Rejected actor for trying to post while not following: %s',
					self.actor.id
				)

				return Response.new_error(401, 'access denied', 'json')

		logging.debug('>> payload %s', self.message.to_json(4))

		await run_processor(self)
		return Response.new(status = 202)


	async def get_post_data(self) -> Response | None:
		try:
			self.signature = aputils.Signature.parse(self.request.headers['signature'])

		except KeyError:
			logging.verbose('Missing signature header')
			return Response.new_error(400, 'missing signature header', 'json')

		try:
			message: Message | None = await self.request.json(loads = Message.parse)

		except Exception:
			traceback.print_exc()
			logging.verbose('Failed to parse inbox message')
			return Response.new_error(400, 'failed to parse message', 'json')

		if message is None:
			logging.verbose('empty message')
			return Response.new_error(400, 'missing message', 'json')

		self.message = message

		if 'actor' not in self.message:
			logging.verbose('actor not in message')
			return Response.new_error(400, 'no actor in message', 'json')

		actor: Message | None = await self.client.get(self.signature.keyid, True, Message)

		if actor is None:
			# ld signatures aren't handled atm, so just ignore it
			if self.message.type == 'Delete':
				logging.verbose('Instance sent a delete which cannot be handled')
				return Response.new(status=202)

			logging.verbose(f'Failed to fetch actor: {self.signature.keyid}')
			return Response.new_error(400, 'failed to fetch actor', 'json')

		self.actor = actor

		try:
			self.signer = self.actor.signer

		except KeyError:
			logging.verbose('Actor missing public key: %s', self.signature.keyid)
			return Response.new_error(400, 'actor missing public key', 'json')

		try:
			await self.signer.validate_request_async(self.request)

		except aputils.SignatureFailureError as e:
			logging.verbose('signature validation failed for "%s": %s', self.actor.id, e)
			return Response.new_error(401, str(e), 'json')

		return None


@register_route('/.well-known/webfinger')
class WebfingerView(View):
	async def get(self, request: Request) -> Response:
		try:
			subject = request.query['resource']

		except KeyError:
			return Response.new_error(400, 'missing "resource" query key', 'json')

		if subject != f'acct:relay@{self.config.domain}':
			return Response.new_error(404, 'user not found', 'json')

		data = aputils.Webfinger.new(
			handle = 'relay',
			domain = self.config.domain,
			actor = self.config.actor
		)

		return Response.new(data, ctype = 'json')
