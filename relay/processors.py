from __future__ import annotations

import tinysql
import typing

from cachetools import LRUCache

from . import logger as logging
from .misc import Message

if typing.TYPE_CHECKING:
	from .views import ActorView


cache = LRUCache(1024)


def person_check(actor: str, software: str) -> bool:
	# pleroma and akkoma may use Person for the actor type for some reason
	# akkoma changed this in 3.6.0
	if software in {'akkoma', 'pleroma'} and actor.id == f'https://{actor.domain}/relay':
		return False

	# make sure the actor is an application
	if actor.type != 'Application':
		return True

	return False


async def handle_relay(view: ActorView) -> None:
	if view.message.object_id in cache:
		logging.verbose('already relayed %s', view.message.object_id)
		return

	message = Message.new_announce(view.config.domain, view.message.object_id)
	cache[view.message.object_id] = message.id
	logging.debug('>> relay: %s', message)

	with view.database.connection() as conn:
		for inbox in conn.distill_inboxes(view.message):
			view.app.push_message(inbox, message)


async def handle_forward(view: ActorView) -> None:
	if view.message.id in cache:
		logging.verbose('already forwarded %s', view.message.id)
		return

	message = Message.new_announce(view.config.domain, view.message)
	cache[view.message.id] = message.id
	logging.debug('>> forward: %s', message)

	with view.database.connection() as conn:
		for inbox in conn.distill_inboxes(view.message):
			view.app.push_message(inbox, message)


async def handle_follow(view: ActorView) -> None:
	nodeinfo = await view.client.fetch_nodeinfo(view.actor.domain)
	software = nodeinfo.sw_name if nodeinfo else None

	with view.database.connection() as conn:
		# reject if software used by actor is banned
		if conn.get_software_ban(software):
			view.app.push_message(
				view.actor.shared_inbox,
				Message.new_response(
					host = view.config.domain,
					actor = view.actor.id,
					followid = view.message.id,
					accept = False
				)
			)

			logging.verbose(
				'Rejected follow from actor for using specific software: actor=%s, software=%s',
				view.actor.id,
				software
			)

			return

		## reject if the actor is not an instance actor
		if person_check(view.actor, software):
			view.app.push_message(
				view.actor.shared_inbox,
				Message.new_response(
					host = view.config.domain,
					actor = view.actor.id,
					followid = view.message.id,
					accept = False
				)
			)

			logging.verbose('Non-application actor tried to follow: %s', view.actor.id)
			return

		if conn.get_inbox(view.actor.shared_inbox):
			data = {'followid': view.message.id}
			statement = tinysql.Update('inboxes', data, inbox = view.actor.shared_inbox)

			with conn.query(statement):
				pass

		else:
			conn.put_inbox(
				view.actor.domain,
				view.actor.shared_inbox,
				view.actor.id,
				view.message.id,
				software
			)

		view.app.push_message(
			view.actor.shared_inbox,
			Message.new_response(
				host = view.config.domain,
				actor = view.actor.id,
				followid = view.message.id,
				accept = True
			)
		)

		# Are Akkoma and Pleroma the only two that expect a follow back?
		# Ignoring only Mastodon for now
		if software != 'mastodon':
			view.app.push_message(
				view.actor.shared_inbox,
				Message.new_follow(
					host = view.config.domain,
					actor = view.actor.id
				)
			)


async def handle_undo(view: ActorView) -> None:
	## If the object is not a Follow, forward it
	if view.message.object['type'] != 'Follow':
		await handle_forward(view)
		return

	with view.database.connection() as conn:
		if not conn.del_inbox(view.actor.id):
			logging.verbose(
				'Failed to delete "%s" with follow ID "%s"',
				view.actor.id,
				view.message.object['id']
			)

	view.app.push_message(
		view.actor.shared_inbox,
		Message.new_unfollow(
			host = view.config.domain,
			actor = view.actor.id,
			follow = view.message
		)
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

	if view.instance:
		if not view.instance['software']:
			if (nodeinfo := await view.client.fetch_nodeinfo(view.instance['domain'])):
				with view.database.connection() as conn:
					view.instance = conn.update_inbox(
						view.instance['inbox'],
						software = nodeinfo.sw_name
					)

		if not view.instance['actor']:
			with view.database.connection() as conn:
				view.instance = conn.update_inbox(
					view.instance['inbox'],
					actor = view.actor.id
				)

	logging.verbose('New "%s" from actor: %s', view.message.type, view.actor.id)
	await processors[view.message.type](view)
