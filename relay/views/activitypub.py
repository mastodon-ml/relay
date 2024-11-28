from __future__ import annotations

import aputils
import traceback

from aiohttp import ClientConnectorError
from aiohttp.web import Request
from aputils import Signature, SignatureFailureError, Signer
from blib import HttpError, HttpMethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import register_route

from .. import logger as logging
from ..database import schema
from ..misc import Message, Response
from ..processors import run_processor

if TYPE_CHECKING:
	from ..application import Application

	try:
		from typing import Self

	except ImportError:
		from typing_extensions import Self


@dataclass(slots = True)
class InboxData:
	signature: Signature
	message: Message
	actor: Message
	signer: Signer
	instance: schema.Instance | None


	@classmethod
	async def parse(cls: type[Self], app: Application, request: Request) -> Self:
		signature: Signature | None = None
		message: Message | None = None
		actor: Message | None = None
		signer: Signer | None = None

		try:
			signature = Signature.parse(request.headers["signature"])

		except KeyError:
			logging.verbose("Missing signature header")
			raise HttpError(400, "missing signature header")

		try:
			message = await request.json(loads = Message.parse)

		except Exception:
			traceback.print_exc()
			logging.verbose("Failed to parse message from actor: %s", signature.keyid)
			raise HttpError(400, "failed to parse message")

		if message is None:
			logging.verbose("empty message")
			raise HttpError(400, "missing message")

		if "actor" not in message:
			logging.verbose("actor not in message")
			raise HttpError(400, "no actor in message")

		try:
			actor = await app.client.get(signature.keyid, True, Message)

		except HttpError as e:
			# ld signatures aren"t handled atm, so just ignore it
			if message.type == "Delete":
				logging.verbose("Instance sent a delete which cannot be handled")
				raise HttpError(202, "")

			logging.verbose("Failed to fetch actor: %s", signature.keyid)
			logging.debug("HTTP Status %i: %s", e.status, e.message)
			raise HttpError(400, "failed to fetch actor")

		except ClientConnectorError as e:
			logging.warning("Error when trying to fetch actor: %s, %s", signature.keyid, str(e))
			raise HttpError(400, "failed to fetch actor")

		except Exception:
			traceback.print_exc()
			raise HttpError(500, "unexpected error when fetching actor")

		try:
			signer = actor.signer

		except KeyError:
			logging.verbose("Actor missing public key: %s", signature.keyid)
			raise HttpError(400, "actor missing public key")

		try:
			await signer.validate_request_async(request)

		except SignatureFailureError as e:
			logging.verbose("signature validation failed for \"%s\": %s", actor.id, e)
			raise HttpError(401, str(e))

		return cls(signature, message, actor, signer, None)


@register_route(HttpMethod.GET, "/actor", "/inbox")
async def handle_actor(app: Application, request: Request) -> Response:
	with app.database.session(False) as conn:
		config = conn.get_config_all()

	data = Message.new_actor(
		host = app.config.domain,
		pubkey = app.signer.pubkey,
		description = app.template.render_markdown(config.note),
		approves = config.approval_required
	)

	return Response.new(data, ctype = "activity")


@register_route(HttpMethod.POST, "/actor", "/inbox")
async def handle_inbox(app: Application, request: Request) -> Response:
	data = await InboxData.parse(app, request)

	with app.database.session() as conn:
		data.instance = conn.get_inbox(data.actor.shared_inbox)

		# reject if actor is banned
		if conn.get_domain_ban(data.actor.domain):
			logging.verbose("Ignored request from banned actor: %s", data.actor.id)
			raise HttpError(403, "access denied")

		# reject if activity type isn"t "Follow" and the actor isn"t following
		if data.message.type != "Follow" and not data.instance:
			logging.verbose(
				"Rejected actor for trying to post while not following: %s",
				data.actor.id
			)

			raise HttpError(401, "access denied")

	logging.debug(">> payload %s", data.message.to_json(4))

	await run_processor(data)
	return Response.new(status = 202)


@register_route(HttpMethod.GET, "/outbox")
async def handle_outbox(app: Application, request: Request) -> Response:
	msg = aputils.Message.new(
		aputils.ObjectType.ORDERED_COLLECTION,
		{
			"id": f"https://{app.config.domain}/outbox",
			"totalItems": 0,
			"orderedItems": []
		}
	)

	return Response.new(msg, ctype = "activity")


@register_route(HttpMethod.GET, "/following", "/followers")
async def handle_follow(app: Application, request: Request) -> Response:
	with app.database.session(False) as s:
		inboxes = [row["actor"] for row in s.get_inboxes()]

	msg = aputils.Message.new(
		aputils.ObjectType.COLLECTION,
		{
			"id": f"https://{app.config.domain}{request.path}",
			"totalItems": len(inboxes),
			"items": inboxes
		}
	)

	return Response.new(msg, ctype = "activity")


@register_route(HttpMethod.GET, "/.well-known/webfinger")
async def get(app: Application, request: Request) -> Response:
	try:
		subject = request.query["resource"]

	except KeyError:
		raise HttpError(400, "missing \"resource\" query key")

	if subject != f"acct:relay@{app.config.domain}":
		raise HttpError(404, "user not found")

	data = aputils.Webfinger.new(
		handle = "relay",
		domain = app.config.domain,
		actor = app.config.actor
	)

	return Response.new(data, ctype = "json")
