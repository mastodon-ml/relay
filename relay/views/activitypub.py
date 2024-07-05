import aputils
import traceback

from aiohttp.web import Request

from .base import View, register_route

from .. import logger as logging
from ..database import schema
from ..misc import HttpError, Message, Response
from ..processors import run_processor


@register_route('/actor', '/inbox')
class ActorView(View):
	signature: aputils.Signature
	message: Message
	actor: Message
	instance: schema.Instance
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
		await self.get_post_data()

		with self.database.session() as conn:
			self.instance = conn.get_inbox(self.actor.shared_inbox) # type: ignore[assignment]

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


	async def get_post_data(self) -> None:
		try:
			self.signature = aputils.Signature.parse(self.request.headers['signature'])

		except KeyError:
			logging.verbose('Missing signature header')
			raise HttpError(400, 'missing signature header')

		try:
			message: Message | None = await self.request.json(loads = Message.parse)

		except Exception:
			traceback.print_exc()
			logging.verbose('Failed to parse inbox message')
			raise HttpError(400, 'failed to parse message')

		if message is None:
			logging.verbose('empty message')
			raise HttpError(400, 'missing message')

		self.message = message

		if 'actor' not in self.message:
			logging.verbose('actor not in message')
			raise HttpError(400, 'no actor in message')

		try:
			self.actor = await self.client.get(self.signature.keyid, True, Message)

		except Exception:
			# ld signatures aren't handled atm, so just ignore it
			if self.message.type == 'Delete':
				logging.verbose('Instance sent a delete which cannot be handled')
				raise HttpError(202, '')

			logging.verbose(f'Failed to fetch actor: {self.signature.keyid}')
			raise HttpError(400, 'failed to fetch actor')

		try:
			self.signer = self.actor.signer

		except KeyError:
			logging.verbose('Actor missing public key: %s', self.signature.keyid)
			raise HttpError(400, 'actor missing public key')

		try:
			await self.signer.validate_request_async(self.request)

		except aputils.SignatureFailureError as e:
			logging.verbose('signature validation failed for "%s": %s', self.actor.id, e)
			raise HttpError(401, str(e))


@register_route('/outbox')
class OutboxView(View):
	async def get(self, request: Request) -> Response:
		msg = aputils.Message.new(
			aputils.ObjectType.ORDERED_COLLECTION,
			{
				"id": f'https://{self.config.domain}/outbox',
				"totalItems": 0,
				"orderedItems": []
			}
		)

		return Response.new(msg, ctype = 'activity')


@register_route('/following', '/followers')
class RelationshipView(View):
	async def get(self, request: Request) -> Response:
		with self.database.session(False) as s:
			inboxes = [row['actor'] for row in s.get_inboxes()]

		msg = aputils.Message.new(
			aputils.ObjectType.COLLECTION,
			{
				"id": f'https://{self.config.domain}{request.path}',
				"totalItems": len(inboxes),
				"items": inboxes
			}
		)

		return Response.new(msg, ctype = 'activity')


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
