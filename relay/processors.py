from __future__ import annotations

import asyncio
import logging
import typing

from cachetools import LRUCache
from uuid import uuid4

from .misc import Message

if typing.TYPE_CHECKING:
	from .misc import View


cache = LRUCache(1024)


def person_check(actor, software):
	## pleroma and akkoma may use Person for the actor type for some reason
	if software in {'akkoma', 'pleroma'} and actor.id == f'https://{actor.domain}/relay':
		return False

	## make sure the actor is an application
	if actor.type != 'Application':
		return True


async def handle_relay(view: View) -> None:
	if view.message.objectid in cache:
		logging.verbose(f'already relayed {view.message.objectid}')
		return

	message = Message.new_announce(
		host = view.config.host,
		object = view.message.objectid
	)

	cache[view.message.objectid] = message.id
	logging.debug(f'>> relay: {message}')

	inboxes = view.database.distill_inboxes(message)

	for inbox in inboxes:
		view.app.push_message(inbox, message)


async def handle_forward(view: View) -> None:
	if view.message.id in cache:
		logging.verbose(f'already forwarded {view.message.id}')
		return

	message = Message.new_announce(
		host = view.config.host,
		object = view.message
	)

	cache[view.message.id] = message.id
	logging.debug(f'>> forward: {message}')

	inboxes = view.database.distill_inboxes(message.message)

	for inbox in inboxes:
		view.app.push_message(inbox, message)


async def handle_follow(view: View) -> None:
	nodeinfo = await view.client.fetch_nodeinfo(view.actor.domain)
	software = nodeinfo.sw_name if nodeinfo else None

	## reject if software used by actor is banned
	if view.config.is_banned_software(software):
		view.app.push_message(
			view.actor.shared_inbox,
			Message.new_response(
				host = view.config.host,
				actor = view.actor.id,
				followid = view.message.id,
				accept = False
			)
		)

		return logging.verbose(f'Rejected follow from actor for using specific software: actor={view.actor.id}, software={software}')

	## reject if the actor is not an instance actor
	if person_check(view.actor, software):
		view.app.push_message(
			view.actor.shared_inbox,
			Message.new_response(
				host = view.config.host,
				actor = view.actor.id,
				followid = view.message.id,
				accept = False
			)
		)

		logging.verbose(f'Non-application actor tried to follow: {view.actor.id}')
		return

	view.database.add_inbox(view.actor.shared_inbox, view.message.id, software)
	view.database.save()

	view.app.push_message(
		view.actor.shared_inbox,
		Message.new_response(
			host = view.config.host,
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
				host = view.config.host,
				actor = view.actor.id
			)
		)


async def handle_undo(view: View) -> None:
	## If the object is not a Follow, forward it
	if view.message.object['type'] != 'Follow':
		return await handle_forward(view)

	if not view.database.del_inbox(view.actor.domain, view.message.object['id']):
		logging.verbose(
			'Failed to delete "%s" with follow ID "%s"',
			view.actor.id,
			view.message.object['id']
		)

		return

	view.database.save()

	view.app.push_message(
		view.actor.shared_inbox,
		Message.new_unfollow(
			host = view.config.host,
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


async def run_processor(view: View):
	if view.message.type not in processors:
		logging.verbose(
				f'Message type "{view.message.type}" from actor cannot be handled: {view.actor.id}'
		)

		return

	if view.instance and not view.instance.get('software'):
		nodeinfo = await view.client.fetch_nodeinfo(view.instance['domain'])

		if nodeinfo:
			view.instance['software'] = nodeinfo.sw_name
			view.database.save()

	logging.verbose(f'New "{view.message.type}" from actor: {view.actor.id}')
	return await processors[view.message.type](view)
