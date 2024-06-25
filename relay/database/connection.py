from __future__ import annotations

from argon2 import PasswordHasher
from bsql import Connection as SqlConnection, Row, Update
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from uuid import uuid4

from . import schema
from .config import (
	THEMES,
	ConfigData
)

from .. import logger as logging
from ..misc import Message, boolean, get_app

if TYPE_CHECKING:
	from ..application import Application

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


	def distill_inboxes(self, message: Message) -> Iterator[schema.Instance]:
		src_domains = {
			message.domain,
			urlparse(message.object_id).netloc
		}

		for instance in self.get_inboxes():
			if instance.domain not in src_domains:
				yield instance


	def get_config(self, key: str) -> Any:
		key = key.replace('_', '-')

		with self.run('get-config', {'key': key}) as cur:
			if (row := cur.one(Row)) is None:
				return ConfigData.DEFAULT(key)

		data = ConfigData()
		data.set(row['key'], row['value'])
		return data.get(key)


	def get_config_all(self) -> ConfigData:
		rows = tuple(self.run('get-config-all', None).all(schema.Row))
		return ConfigData.from_rows(rows)


	def put_config(self, key: str, value: Any) -> Any:
		field = ConfigData.FIELD(key)
		key = field.name.replace('_', '-')

		if key == 'private-key':
			self.app.signer = value

		elif key == 'log-level':
			value = logging.LogLevel.parse(value)
			logging.set_level(value)
			self.app['workers'].set_log_level(value)

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
			'type': 'LogLevel' if field.type == 'logging.LogLevel' else field.type # type: ignore
		}

		with self.run('put-config', params):
			pass

		return data.get(key)


	def get_inbox(self, value: str) -> schema.Instance | None:
		with self.run('get-inbox', {'value': value}) as cur:
			return cur.one(schema.Instance)


	def get_inboxes(self) -> Iterator[schema.Instance]:
		return self.execute("SELECT * FROM inboxes WHERE accepted = 1").all(schema.Instance)


	def put_inbox(self,
				domain: str,
				inbox: str | None = None,
				actor: str | None = None,
				followid: str | None = None,
				software: str | None = None,
				accepted: bool = True) -> schema.Instance:

		params: dict[str, Any] = {
			'inbox': inbox,
			'actor': actor,
			'followid': followid,
			'software': software,
			'accepted': accepted
		}

		if self.get_inbox(domain) is None:
			if not inbox:
				raise ValueError("Missing inbox")

			params['domain'] = domain
			params['created'] = datetime.now(tz = timezone.utc)

			with self.run('put-inbox', params) as cur:
				if (row := cur.one(schema.Instance)) is None:
					raise RuntimeError(f"Failed to insert instance: {domain}")

				return row

		for key, value in tuple(params.items()):
			if value is None:
				del params[key]

		with self.update('inboxes', params, domain = domain) as cur:
			if (row := cur.one(schema.Instance)) is None:
				raise RuntimeError(f"Failed to update instance: {domain}")

			return row


	def del_inbox(self, value: str) -> bool:
		with self.run('del-inbox', {'value': value}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_request(self, domain: str) -> schema.Instance | None:
		with self.run('get-request', {'domain': domain}) as cur:
			return cur.one(schema.Instance)


	def get_requests(self) -> Iterator[schema.Instance]:
		return self.execute('SELECT * FROM inboxes WHERE accepted = 0').all(schema.Instance)


	def put_request_response(self, domain: str, accepted: bool) -> schema.Instance:
		if (instance := self.get_request(domain)) is None:
			raise KeyError(domain)

		if not accepted:
			if not self.del_inbox(domain):
				raise RuntimeError(f'Failed to delete request: {domain}')

			return instance

		params = {
			'domain': domain,
			'accepted': accepted
		}

		with self.run('put-inbox-accept', params) as cur:
			if (row := cur.one(schema.Instance)) is None:
				raise RuntimeError(f"Failed to insert response for domain: {domain}")

			return row


	def get_user(self, value: str) -> schema.User | None:
		with self.run('get-user', {'value': value}) as cur:
			return cur.one(schema.User)


	def get_user_by_token(self, code: str) -> schema.User | None:
		with self.run('get-user-by-token', {'code': code}) as cur:
			return cur.one(schema.User)


	def get_users(self) -> Iterator[schema.User]:
		return self.execute("SELECT * FROM users").all(schema.User)


	def put_user(self, username: str, password: str | None, handle: str | None = None) -> schema.User:
		if self.get_user(username) is not None:
			data: dict[str, str | datetime | None] = {}

			if password:
				data['hash'] = self.hasher.hash(password)

			if handle:
				data['handle'] = handle

			stmt = Update("users", data)
			stmt.set_where("username", username)

			with self.query(stmt) as cur:
				if (row := cur.one(schema.User)) is None:
					raise RuntimeError(f"Failed to update user: {username}")

				return row

		if password is None:
			raise ValueError('Password cannot be empty')

		data = {
			'username': username,
			'hash': self.hasher.hash(password),
			'handle': handle,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-user', data) as cur:
			if (row := cur.one(schema.User)) is None:
				raise RuntimeError(f"Failed to insert user: {username}")

			return row


	def del_user(self, username: str) -> None:
		if (user := self.get_user(username)) is None:
			raise KeyError(username)

		with self.run('del-user', {'value': user.username}):
			pass

		with self.run('del-token-user', {'username': user.username}):
			pass


	def get_token(self, code: str) -> schema.Token | None:
		with self.run('get-token', {'code': code}) as cur:
			return cur.one(schema.Token)


	def get_tokens(self, username: str | None = None) -> Iterator[schema.Token]:
		if username is not None:
			return self.select('tokens').all(schema.Token)

		return self.select('tokens', username = username).all(schema.Token)


	def put_token(self, username: str) -> schema.Token:
		data = {
			'code': uuid4().hex,
			'user': username,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-token', data) as cur:
			if (row := cur.one(schema.Token)) is None:
				raise RuntimeError(f"Failed to insert token for user: {username}")

			return row


	def del_token(self, code: str) -> None:
		with self.run('del-token', {'code': code}):
			pass


	def get_domain_ban(self, domain: str) -> schema.DomainBan | None:
		if domain.startswith('http'):
			domain = urlparse(domain).netloc

		with self.run('get-domain-ban', {'domain': domain}) as cur:
			return cur.one(schema.DomainBan)


	def get_domain_bans(self) -> Iterator[schema.DomainBan]:
		return self.execute("SELECT * FROM domain_bans").all(schema.DomainBan)


	def put_domain_ban(self,
							domain: str,
							reason: str | None = None,
							note: str | None = None) -> schema.DomainBan:

		params = {
			'domain': domain,
			'reason': reason,
			'note': note,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-domain-ban', params) as cur:
			if (row := cur.one(schema.DomainBan)) is None:
				raise RuntimeError(f"Failed to insert domain ban: {domain}")

			return row


	def update_domain_ban(self,
						domain: str,
						reason: str | None = None,
						note: str | None = None) -> schema.DomainBan:

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

			if (row := cur.one(schema.DomainBan)) is None:
				raise RuntimeError(f"Failed to update domain ban: {domain}")

			return row


	def del_domain_ban(self, domain: str) -> bool:
		with self.run('del-domain-ban', {'domain': domain}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_software_ban(self, name: str) -> schema.SoftwareBan | None:
		with self.run('get-software-ban', {'name': name}) as cur:
			return cur.one(schema.SoftwareBan)


	def get_software_bans(self) -> Iterator[schema.SoftwareBan,]:
		return self.execute('SELECT * FROM software_bans').all(schema.SoftwareBan)


	def put_software_ban(self,
							name: str,
							reason: str | None = None,
							note: str | None = None) -> schema.SoftwareBan:

		params = {
			'name': name,
			'reason': reason,
			'note': note,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-software-ban', params) as cur:
			if (row := cur.one(schema.SoftwareBan)) is None:
				raise RuntimeError(f'Failed to insert software ban: {name}')

			return row


	def update_software_ban(self,
						name: str,
						reason: str | None = None,
						note: str | None = None) -> schema.SoftwareBan:

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

			if (row := cur.one(schema.SoftwareBan)) is None:
				raise RuntimeError(f'Failed to update software ban: {name}')

			return row


	def del_software_ban(self, name: str) -> bool:
		with self.run('del-software-ban', {'name': name}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1


	def get_domain_whitelist(self, domain: str) -> schema.Whitelist | None:
		with self.run('get-domain-whitelist', {'domain': domain}) as cur:
			return cur.one()


	def get_domains_whitelist(self) -> Iterator[schema.Whitelist,]:
		return self.execute("SELECT * FROM whitelist").all(schema.Whitelist)


	def put_domain_whitelist(self, domain: str) -> schema.Whitelist:
		params = {
			'domain': domain,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.run('put-domain-whitelist', params) as cur:
			if (row := cur.one(schema.Whitelist)) is None:
				raise RuntimeError(f'Failed to insert whitelisted domain: {domain}')

			return row


	def del_domain_whitelist(self, domain: str) -> bool:
		with self.run('del-domain-whitelist', {'domain': domain}) as cur:
			if cur.row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.row_count == 1
