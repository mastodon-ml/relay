from __future__ import annotations

import typing

from . import logger as logging
from .database import Connection
from .misc import Message

if typing.TYPE_CHECKING:
	from .views.activitypub import ActorView


def actor_type_check(actor: Message, software: str | None) -> bool:
	if actor.type == 'Application':
		return True

	# akkoma (< 3.6.0) and pleroma use Person for the actor type
	if software in {'akkoma', 'pleroma'} and actor.id == f'https://{actor.domain}/relay':
		return True

	return False


async def handle_relay(view: ActorView, conn: Connection) -> None:
	try:
		view.cache.get('handle-relay', view.message.object_id)
		logging.verbose('already relayed %s', view.message.object_id)
		return

	except KeyError:
		pass

	message = Message.new_announce(view.config.domain, view.message.object_id)
	logging.debug('>> relay: %s', message)

	for instance in conn.distill_inboxes(view.message):
		view.app.push_message(instance.inbox, message, instance)

	view.cache.set('handle-relay', view.message.object_id, message.id, 'str')


async def handle_forward(view: ActorView, conn: Connection) -> None:
	try:
		view.cache.get('handle-relay', view.message.id)
		logging.verbose('already forwarded %s', view.message.id)
		return

	except KeyError:
		pass

	message = Message.new_announce(view.config.domain, view.message)
	logging.debug('>> forward: %s', message)

	for instance in conn.distill_inboxes(view.message):
		view.app.push_message(instance.inbox, view.message, instance)

	view.cache.set('handle-relay', view.message.id, message.id, 'str')


async def handle_follow(view: ActorView, conn: Connection) -> None:
	nodeinfo = await view.client.fetch_nodeinfo(view.actor.domain, force = True)
	software = nodeinfo.sw_name if nodeinfo else None
	config = conn.get_config_all()

	# reject if software used by actor is banned
	if software and conn.get_software_ban(software):
		logging.verbose('Rejected banned actor: %s', view.actor.id)

		view.app.push_message(
			view.actor.shared_inbox,
			Message.new_response(
				host = view.config.domain,
				actor = view.actor.id,
				followid = view.message.id,
				accept = False
			),
			view.instance
		)

		logging.verbose(
			'Rejected follow from actor for using specific software: actor=%s, software=%s',
			view.actor.id,
			software
		)

		return

	# reject if the actor is not an instance actor
	if actor_type_check(view.actor, software):
		logging.verbose('Non-application actor tried to follow: %s', view.actor.id)

		view.app.push_message(
			view.actor.shared_inbox,
			Message.new_response(
				host = view.config.domain,
				actor = view.actor.id,
				followid = view.message.id,
				accept = False
			),
			view.instance
		)

		return

	if not conn.get_domain_whitelist(view.actor.domain):
		# add request if approval-required is enabled
		if config.approval_required:
			logging.verbose('New follow request fromm actor: %s', view.actor.id)

			with conn.transaction():
				view.instance = conn.put_inbox(
					domain = view.actor.domain,
					inbox = view.actor.shared_inbox,
					actor = view.actor.id,
					followid = view.message.id,
					software = software,
					accepted = False
				)

			return

		# reject if the actor isn't whitelisted while the whiltelist is enabled
		if config.whitelist_enabled:
			logging.verbose('Rejected actor for not being in the whitelist: %s', view.actor.id)

			view.app.push_message(
				view.actor.shared_inbox,
				Message.new_response(
					host = view.config.domain,
					actor = view.actor.id,
					followid = view.message.id,
					accept = False
				),
				view.instance
			)

			return

	with conn.transaction():
		view.instance = conn.put_inbox(
				domain = view.actor.domain,
				inbox = view.actor.shared_inbox,
				actor = view.actor.id,
				followid = view.message.id,
				software = software,
				accepted = True
			)

	view.app.push_message(
		view.actor.shared_inbox,
		Message.new_response(
			host = view.config.domain,
			actor = view.actor.id,
			followid = view.message.id,
			accept = True
		),
		view.instance
	)

	# Are Akkoma and Pleroma the only two that expect a follow back?
	# Ignoring only Mastodon for now
	if software != 'mastodon':
		view.app.push_message(
			view.actor.shared_inbox,
			Message.new_follow(
				host = view.config.domain,
				actor = view.actor.id
			),
			view.instance
		)


async def handle_undo(view: ActorView, conn: Connection) -> None:
	if view.message.object['type'] != 'Follow':
		# forwarding deletes does not work, so don't bother
		# await handle_forward(view, conn)
		return

	# prevent past unfollows from removing an instance
	if view.instance.followid and view.instance.followid != view.message.object_id:
		return

	with conn.transaction():
		if not conn.del_inbox(view.actor.id):
			logging.verbose(
				'Failed to delete "%s" with follow ID "%s"',
				view.actor.id,
				view.message.object_id
			)

	view.app.push_message(
		view.actor.shared_inbox,
		Message.new_unfollow(
			host = view.config.domain,
			actor = view.actor.id,
			follow = view.message
		),
		view.instance
	)


processors = {
	'Announce': handle_relay,
	'Create': handle_relay,
	'Delete': handle_forward,
	'Follow': handle_follow,
	'Undo': handle_undo,
	'Update': handle_forward,
}


async def run_processor(view: ActorView) -> None:
	if view.message.type not in processors:
		logging.verbose(
			'Message type "%s" from actor cannot be handled: %s',
			view.message.type,
			view.actor.id
		)

		return

	with view.database.session() as conn:
		if view.instance:
			if not view.instance.software:
				if (nodeinfo := await view.client.fetch_nodeinfo(view.instance.domain)):
					with conn.transaction():
						view.instance = conn.put_inbox(
							domain = view.instance.domain,
							software = nodeinfo.sw_name
						)

			if not view.instance.actor:
				with conn.transaction():
					view.instance = conn.put_inbox(
						domain = view.instance.domain,
						actor = view.actor.id
					)

		logging.verbose('New "%s" from actor: %s', view.message.type, view.actor.id)
		await processors[view.message.type](view, conn)
