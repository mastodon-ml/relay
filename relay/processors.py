from __future__ import annotations

from typing import TYPE_CHECKING, cast

from . import logger as logging
from .database import Connection
from .database.schema import Instance
from .misc import Message, get_state

if TYPE_CHECKING:
	from .state import State
	from .views.activitypub import InboxData


def is_application(actor: Message, software: str | None) -> bool:
	if actor.type == "Application":
		return True

	# akkoma (< 3.6.0) and pleroma use Person for the actor type
	if software in {"akkoma", "pleroma"} and actor.id == f"https://{actor.domain}/relay":
		return True

	return False


async def handle_relay(state: State, data: InboxData, conn: Connection) -> None:
	try:
		state.cache.get("handle-relay", data.message.object_id)
		logging.verbose("already relayed %s", data.message.object_id)
		return

	except KeyError:
		pass

	message = Message.new_announce(state.config.domain, data.message.object_id)
	logging.debug(">> relay: %s", message)

	for instance in conn.distill_inboxes(data.message):
		state.push_message(instance.inbox, message, instance)

	state.cache.set("handle-relay", data.message.object_id, message.id, "str")


async def handle_forward(state: State, data: InboxData, conn: Connection) -> None:
	try:
		state.cache.get("handle-relay", data.message.id)
		logging.verbose("already forwarded %s", data.message.id)
		return

	except KeyError:
		pass

	message = Message.new_announce(state.config.domain, data.message)
	logging.debug(">> forward: %s", message)

	for instance in conn.distill_inboxes(data.message):
		state.push_message(instance.inbox, data.message, instance)

	state.cache.set("handle-relay", data.message.id, message.id, "str")


async def handle_follow(state: State, data: InboxData, conn: Connection) -> None:
	nodeinfo = await state.client.fetch_nodeinfo(data.actor.domain, force = True)
	software = nodeinfo.sw_name if nodeinfo else None
	config = conn.get_config_all()

	# reject if software used by actor is banned
	if software and conn.get_software_ban(software):
		state.push_message(
			data.shared_inbox,
			Message.new_response(
				host = state.config.domain,
				actor = data.actor.id,
				followid = data.message.id,
				accept = False
			),
			cast(Instance, data.instance)
		)

		logging.verbose(
			"Rejected follow from actor for using specific software: actor=%s, software=%s",
			data.actor.id,
			software
		)

		return

	# reject if the actor is not an instance actor
	if not is_application(data.actor, software):
		logging.verbose("Non-application actor tried to follow: %s", data.actor.id)

		state.push_message(
			data.shared_inbox,
			Message.new_response(
				host = state.config.domain,
				actor = data.actor.id,
				followid = data.message.id,
				accept = False
			),
			cast(Instance, data.instance)
		)

		return

	if not conn.get_domain_whitelist(data.actor.domain):
		# add request if approval-required is enabled
		if config.approval_required:
			logging.verbose("New follow request fromm actor: %s", data.actor.id)

			with conn.transaction():
				data.instance = conn.put_inbox(
					domain = data.actor.domain,
					inbox = data.shared_inbox,
					actor = data.actor.id,
					followid = data.message.id,
					software = software,
					accepted = False
				)

			return

		# reject if the actor isn"t whitelisted while the whiltelist is enabled
		if config.whitelist_enabled:
			logging.verbose("Rejected actor for not being in the whitelist: %s", data.actor.id)

			state.push_message(
				data.shared_inbox,
				Message.new_response(
					host = state.config.domain,
					actor = data.actor.id,
					followid = data.message.id,
					accept = False
				),
				cast(Instance, data.instance)
			)

			return

	with conn.transaction():
		data.instance = conn.put_inbox(
				domain = data.actor.domain,
				inbox = data.shared_inbox,
				actor = data.actor.id,
				followid = data.message.id,
				software = software,
				accepted = True
			)

	state.push_message(
		data.shared_inbox,
		Message.new_response(
			host = state.config.domain,
			actor = data.actor.id,
			followid = data.message.id,
			accept = True
		),
		data.instance
	)

	# Are Akkoma and Pleroma the only two that expect a follow back?
	# Ignoring only Mastodon for now
	if software != "mastodon":
		state.push_message(
			data.shared_inbox,
			Message.new_follow(
				host = state.config.domain,
				actor = data.actor.id
			),
			data.instance
		)


async def handle_undo(state: State, data: InboxData, conn: Connection) -> None:
	if data.message.object["type"] != "Follow":
		# forwarding deletes does not work, so don"t bother
		# await handle_forward(state, data, conn)
		return

	if data.instance is None:
		raise ValueError(f"Actor not in database: {data.actor.id}")

	# prevent past unfollows from removing an instance
	if data.instance.followid and data.instance.followid != data.message.object_id:
		return

	with conn.transaction():
		if not conn.del_inbox(data.actor.id):
			logging.verbose(
				"Failed to delete \"%s\" with follow ID \"%s\"",
				data.actor.id,
				data.message.object_id
			)

	state.push_message(
		data.shared_inbox,
		Message.new_unfollow(
			host = state.config.domain,
			actor = data.actor.id,
			follow = data.message
		),
		data.instance
	)


processors = {
	"Announce": handle_relay,
	"Create": handle_relay,
	"Delete": handle_forward,
	"Follow": handle_follow,
	"Undo": handle_undo,
	"Update": handle_forward,
}


async def run_processor(data: InboxData) -> None:
	if data.message.type not in processors:
		logging.verbose(
			"Message type \"%s\" from actor cannot be handled: %s",
			data.message.type,
			data.actor.id
		)

		return

	state = get_state()

	with state.database.session() as conn:
		if data.instance:
			if not data.instance.software:
				if (nodeinfo := await state.client.fetch_nodeinfo(data.instance.domain)):
					with conn.transaction():
						data.instance = conn.put_inbox(
							domain = data.instance.domain,
							software = nodeinfo.sw_name
						)

			if not data.instance.actor:
				with conn.transaction():
					data.instance = conn.put_inbox(
						domain = data.instance.domain,
						actor = data.actor.id
					)

		logging.verbose("New \"%s\" from actor: %s", data.message.type, data.actor.id)
		await processors[data.message.type](state, data, conn)
