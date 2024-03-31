from __future__ import annotations

import typing

from argon2 import PasswordHasher
from bsql import Connection as SqlConnection, Update
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from .config import (
	THEMES,
	ConfigData
)

from .. import logger as logging
from ..misc import boolean, get_app

if typing.TYPE_CHECKING:
	from collections.abc import Iterator, Sequence
	from bsql import Row
	from typing import Any
	from ..application import Application
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


	def distill_inboxes(self, message: Message) -> Iterator[Row]:
		src_domains = {
			message.domain,
			urlparse(message.object_id).netloc
		}

		for instance in self.get_inboxes():
			if instance['domain'] not in src_domains:
				yield instance


	def get_config(self, key: str) -> Any:
		key = key.replace('_', '-')

		with self.run('get-config', {'key': key}) as cur:
			if not (row := cur.one()):
				return ConfigData.DEFAULT(key)

		data = ConfigData()
		data.set(row['key'], row['value'])
		return data.get(key)


	def get_config_all(self) -> ConfigData:
		with self.run('get-config-all', None) as cur:
			return ConfigData.from_rows(tuple(cur.all()))


	def put_config(self, key: str, value: Any) -> Any:
		field = ConfigData.FIELD(key)
		key = field.name.replace('_', '-')

		if key == 'private-key':
			self.app.signer = value

		elif key == 'log-level':
			value = logging.LogLevel.parse(value)
			logging.set_level(value)

		elif key in {'approval-required', 'whitelist-enabled'}:
			value = boolean(value)

		elif key == 'theme':
			if value not in THEMES:
				raise ValueError(f'"{value}" is not a valid theme')

		data = ConfigData()
		data.set(key, value)

		params = {
			'key': key,
			'value': data.get(key, serialize = True),
			'type': 'LogLevel' if field.type == 'logging.LogLevel' else field.type
		}

		with self.run('put-config', params):
			pass

		return data.get(key)


	def get_inbox(self, value: str) -> Row:
		with self.run('get-inbox', {'value': value}) as cur:
			return cur.one() # type: ignore


	def get_inboxes(self) -> Sequence[Row]:
		with self.execute("SELECT * FROM inboxes WHERE accepted = 1") as cur:
			return tuple(cur.all())


	def put_inbox(self,
				domain: str,
				inbox: str | None = None,
				actor: str | None = None,
				followid: str | None = None,
				software: str | None = None,
				accepted: bool = True) -> Row:

		params: dict[str, Any] = {
			'inbox': inbox,
			'actor': actor,
			'followid': followid,
			'software': software,
			'accepted': accepted
		}

		if not self.get_inbox(domain):
			if not inbox:
				raise ValueError("Missing inbox")

			params['domain'] = domain
			params['created'] = datetime.now(tz = timezone.utc)

			with self.run('put-inbox', params) as cur:
				return cur.one() # type: ignore

		for key, value in tuple(params.items()):
			if value is None:
				del params[key]

		with self.update('inboxes', params, domain = domain) as cur:
			return cur.one() # type: ignore


	def del_inbox(self, value: str) -> bool:
		with self.run('del-inbox', {'value': value}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_request(self, domain: str) -> Row:
		with self.run('get-request', {'domain': domain}) as cur:
			if not (row := cur.one()):
				raise KeyError(domain)

			return row


	def get_requests(self) -> Sequence[Row]:
		with self.execute('SELECT * FROM inboxes WHERE accepted = 0') as cur:
			return tuple(cur.all())


	def put_request_response(self, domain: str, accepted: bool) -> Row:
		instance = self.get_request(domain)

		if not accepted:
			self.del_inbox(domain)
			return instance

		params = {
			'domain': domain,
			'accepted': accepted
		}

		with self.run('put-inbox-accept', params) as cur:
			return cur.one() # type: ignore


	def get_user(self, value: str) -> Row:
		with self.run('get-user', {'value': value}) as cur:
			return cur.one() # type: ignore


	def get_user_by_token(self, code: str) -> Row:
		with self.run('get-user-by-token', {'code': code}) as cur:
			return cur.one() # type: ignore


	def put_user(self, username: str, password: str | None, handle: str | None = None) -> Row:
		if self.get_user(username):
			data: dict[str, str | datetime | None] = {}

			if password:
				data['hash'] = self.hasher.hash(password)

			if handle:
				data['handle'] = handle

			stmt = Update("users", data)
			stmt.set_where("username", username)

			with self.query(stmt) as cur:
				return cur.one() # type: ignore

		if password is None:
			raise ValueError('Password cannot be empty')

		data = {
			'username': username,
			'hash': self.hasher.hash(password),
			'handle': handle,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-user', data) as cur:
			return cur.one() # type: ignore


	def del_user(self, username: str) -> None:
		user = self.get_user(username)

		with self.run('del-user', {'value': user['username']}):
			pass

		with self.run('del-token-user', {'username': user['username']}):
			pass


	def get_token(self, code: str) -> Row:
		with self.run('get-token', {'code': code}) as cur:
			return cur.one() # type: ignore


	def put_token(self, username: str) -> Row:
		data = {
			'code': uuid4().hex,
			'user': username,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-token', data) as cur:
			return cur.one() # type: ignore


	def del_token(self, code: str) -> None:
		with self.run('del-token', {'code': code}):
			pass


	def get_domain_ban(self, domain: str) -> Row:
		if domain.startswith('http'):
			domain = urlparse(domain).netloc

		with self.run('get-domain-ban', {'domain': domain}) as cur:
			return cur.one() # type: ignore


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
			return cur.one() # type: ignore


	def update_domain_ban(self,
						domain: str,
						reason: str | None = None,
						note: str | None = None) -> Row:

		if not (reason or note):
			raise ValueError('"reason" and/or "note" must be specified')

		params = {}

		if reason is not None:
			params['reason'] = reason

		if note is not None:
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
			return cur.one() # type: ignore


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
			return cur.one() # type: ignore


	def update_software_ban(self,
						name: str,
						reason: str | None = None,
						note: str | None = None) -> Row:

		if not (reason or note):
			raise ValueError('"reason" and/or "note" must be specified')

		params = {}

		if reason is not None:
			params['reason'] = reason

		if note is not None:
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
			return cur.one() # type: ignore


	def put_domain_whitelist(self, domain: str) -> Row:
		params = {
			'domain': domain,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-domain-whitelist', params) as cur:
			return cur.one() # type: ignore


	def del_domain_whitelist(self, domain: str) -> bool:
		with self.run('del-domain-whitelist', {'domain': domain}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1
