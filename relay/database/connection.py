from __future__ import annotations

import typing

from argon2 import PasswordHasher
from bsql import Connection as SqlConnection, Update
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from .config import (
	CONFIG_DEFAULTS,
	THEMES,
	get_default_type,
	get_default_value,
	serialize,
	deserialize
)

from .. import logger as logging
from ..misc import boolean, get_app

if typing.TYPE_CHECKING:
	from collections.abc import Iterator
	from bsql import Row
	from typing import Any
	from .application import Application
	from ..misc import Message


RELAY_SOFTWARE = [
	'activityrelay', # https://git.pleroma.social/pleroma/relay
	'activity-relay', # https://github.com/yukimochi/Activity-Relay
	'aoderelay', # https://git.asonix.dog/asonix/relay
	'feditools-relay' # https://git.ptzo.gdn/feditools/relay
]


class Connection(SqlConnection):
	hasher = PasswordHasher(
		encoding = 'utf-8'
	)

	@property
	def app(self) -> Application:
		return get_app()


	def distill_inboxes(self, message: Message) -> Iterator[str]:
		src_domains = {
			message.domain,
			urlparse(message.object_id).netloc
		}

		for inbox in self.execute('SELECT * FROM inboxes'):
			if inbox['domain'] not in src_domains:
				yield inbox['inbox']


	def get_config(self, key: str) -> Any:
		if key not in CONFIG_DEFAULTS:
			raise KeyError(key)

		with self.run('get-config', {'key': key}) as cur:
			if not (row := cur.one()):
				return get_default_value(key)

		if row['value']:
			return deserialize(row['key'], row['value'])

		return None


	def get_config_all(self) -> dict[str, Any]:
		with self.run('get-config-all', None) as cur:
			db_config = {row['key']: row['value'] for row in cur}

		config = {}

		for key, data in CONFIG_DEFAULTS.items():
			try:
				config[key] = deserialize(key, db_config[key])

			except KeyError:
				if key == 'schema-version':
					config[key] = 0

				else:
					config[key] = data[1]

		return config


	def put_config(self, key: str, value: Any) -> Any:
		if key not in CONFIG_DEFAULTS:
			raise KeyError(key)

		if key == 'private-key':
			self.app.signer = value

		elif key == 'log-level':
			value = logging.LogLevel.parse(value)
			logging.set_level(value)

		elif key == 'whitelist-enabled':
			value = boolean(value)

		elif key == 'theme':
			if value not in THEMES:
				raise ValueError(f'"{value}" is not a valid theme')

		params = {
			'key': key,
			'value': serialize(key, value) if value is not None else None,
			'type': get_default_type(key)
		}

		with self.run('put-config', params):
			return value


	def get_inbox(self, value: str) -> Row:
		with self.run('get-inbox', {'value': value}) as cur:
			return cur.one()


	def put_inbox(self,
				domain: str,
				inbox: str,
				actor: str | None = None,
				followid: str | None = None,
				software: str | None = None) -> Row:

		params = {
			'domain': domain,
			'inbox': inbox,
			'actor': actor,
			'followid': followid,
			'software': software,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-inbox', params) as cur:
			return cur.one()


	def update_inbox(self,
					inbox: str,
					actor: str | None = None,
					followid: str | None = None,
					software: str | None = None) -> Row:

		if not (actor or followid or software):
			raise ValueError('Missing "actor", "followid", and/or "software"')

		data = {}

		if actor:
			data['actor'] = actor

		if followid:
			data['followid'] = followid

		if software:
			data['software'] = software

		statement = Update('inboxes', data)
		statement.set_where("inbox", inbox)

		with self.query(statement):
			return self.get_inbox(inbox)


	def del_inbox(self, value: str) -> bool:
		with self.run('del-inbox', {'value': value}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_user(self, value: str) -> Row:
		with self.run('get-user', {'value': value}) as cur:
			return cur.one()


	def get_user_by_token(self, code: str) -> Row:
		with self.run('get-user-by-token', {'code': code}) as cur:
			return cur.one()


	def put_user(self, username: str, password: str, handle: str | None = None) -> Row:
		data = {
			'username': username,
			'hash': self.hasher.hash(password),
			'handle': handle,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-user', data) as cur:
			return cur.one()


	def del_user(self, username: str) -> None:
		user = self.get_user(username)

		with self.run('del-user', {'value': user['username']}):
			pass

		with self.run('del-token-user', {'username': user['username']}):
			pass


	def get_token(self, code: str) -> Row:
		with self.run('get-token', {'code': code}) as cur:
			return cur.one()


	def put_token(self, username: str) -> Row:
		data = {
			'code': uuid4().hex,
			'user': username,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-token', data) as cur:
			return cur.one()


	def del_token(self, code: str) -> None:
		with self.run('del-token', {'code': code}):
			pass


	def get_domain_ban(self, domain: str) -> Row:
		if domain.startswith('http'):
			domain = urlparse(domain).netloc

		with self.run('get-domain-ban', {'domain': domain}) as cur:
			return cur.one()


	def put_domain_ban(self,
							domain: str,
							reason: str | None = None,
							note: str | None = None) -> Row:

		params = {
			'domain': domain,
			'reason': reason,
			'note': note,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-domain-ban', params) as cur:
			return cur.one()


	def update_domain_ban(self,
						domain: str,
						reason: str | None = None,
						note: str | None = None) -> Row:

		if not (reason or note):
			raise ValueError('"reason" and/or "note" must be specified')

		params = {}

		if reason:
			params['reason'] = reason

		if note:
			params['note'] = note

		statement = Update('domain_bans', params)
		statement.set_where("domain", domain)

		with self.query(statement) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

		return self.get_domain_ban(domain)


	def del_domain_ban(self, domain: str) -> bool:
		with self.run('del-domain-ban', {'domain': domain}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_software_ban(self, name: str) -> Row:
		with self.run('get-software-ban', {'name': name}) as cur:
			return cur.one()


	def put_software_ban(self,
							name: str,
							reason: str | None = None,
							note: str | None = None) -> Row:

		params = {
			'name': name,
			'reason': reason,
			'note': note,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-software-ban', params) as cur:
			return cur.one()


	def update_software_ban(self,
						name: str,
						reason: str | None = None,
						note: str | None = None) -> Row:

		if not (reason or note):
			raise ValueError('"reason" and/or "note" must be specified')

		params = {}

		if reason:
			params['reason'] = reason

		if note:
			params['note'] = note

		statement = Update('software_bans', params)
		statement.set_where("name", name)

		with self.query(statement) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

		return self.get_software_ban(name)


	def del_software_ban(self, name: str) -> bool:
		with self.run('del-software-ban', {'name': name}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_domain_whitelist(self, domain: str) -> Row:
		with self.run('get-domain-whitelist', {'domain': domain}) as cur:
			return cur.one()


	def put_domain_whitelist(self, domain: str) -> Row:
		params = {
			'domain': domain,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-domain-whitelist', params) as cur:
			return cur.one()


	def del_domain_whitelist(self, domain: str) -> bool:
		with self.run('del-domain-whitelist', {'domain': domain}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1
