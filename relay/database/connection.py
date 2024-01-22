from __future__ import annotations

import tinysql
import typing

from datetime import datetime, timezone
from urllib.parse import urlparse

from .config import CONFIG_DEFAULTS, get_default_type, get_default_value, serialize, deserialize

from .. import logger as logging
from ..misc import get_app

if typing.TYPE_CHECKING:
	from tinysql import Cursor, Row
	from typing import Any, Iterator, Optional
	from .application import Application
	from ..misc import Message


RELAY_SOFTWARE = [
	'activityrelay', # https://git.pleroma.social/pleroma/relay
	'activity-relay', # https://github.com/yukimochi/Activity-Relay
	'aoderelay', # https://git.asonix.dog/asonix/relay
	'feditools-relay' # https://git.ptzo.gdn/feditools/relay
]


class Connection(tinysql.Connection):
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


	def exec_statement(self, name: str, params: Optional[dict[str, Any]] = None) -> Cursor:
		return self.execute(self.database.prepared_statements[name], params)


	def get_config(self, key: str) -> Any:
		if key not in CONFIG_DEFAULTS:
			raise KeyError(key)

		with self.exec_statement('get-config', {'key': key}) as cur:
			if not (row := cur.one()):
				return get_default_value(key)

		if row['value']:
			return deserialize(row['key'], row['value'])

		return None


	def get_config_all(self) -> dict[str, Any]:
		with self.exec_statement('get-config-all') as cur:
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

		params = {
			'key': key,
			'value': serialize(key, value) if value is not None else None,
			'type': get_default_type(key)
		}

		with self.exec_statement('put-config', params):
			return value


	def get_inbox(self, value: str) -> Row:
		with self.exec_statement('get-inbox', {'value': value}) as cur:
			return cur.one()


	def put_inbox(self,
				domain: str,
				inbox: str,
				actor: Optional[str] = None,
				followid: Optional[str] = None,
				software: Optional[str] = None) -> Row:

		params = {
			'domain': domain,
			'inbox': inbox,
			'actor': actor,
			'followid': followid,
			'software': software,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.exec_statement('put-inbox', params) as cur:
			return cur.one()


	def update_inbox(self,
					inbox: str,
					actor: Optional[str] = None,
					followid: Optional[str] = None,
					software: Optional[str] = None) -> Row:

		if not (actor or followid or software):
			raise ValueError('Missing "actor", "followid", and/or "software"')

		data = {}

		if actor:
			data['actor'] = actor

		if followid:
			data['followid'] = followid

		if software:
			data['software'] = software

		statement = tinysql.Update('inboxes', data, inbox = inbox)

		with self.query(statement):
			return self.get_inbox(inbox)


	def del_inbox(self, value: str) -> bool:
		with self.exec_statement('del-inbox', {'value': value}) as cur:
			if cur.modified_row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.modified_row_count == 1


	def get_domain_ban(self, domain: str) -> Row:
		if domain.startswith('http'):
			domain = urlparse(domain).netloc

		with self.exec_statement('get-domain-ban', {'domain': domain}) as cur:
			return cur.one()


	def put_domain_ban(self,
							domain: str,
							reason: Optional[str] = None,
							note: Optional[str] = None) -> Row:

		params = {
			'domain': domain,
			'reason': reason,
			'note': note,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.exec_statement('put-domain-ban', params) as cur:
			return cur.one()


	def update_domain_ban(self,
						domain: str,
						reason: Optional[str] = None,
						note: Optional[str] = None) -> tinysql.Row:

		if not (reason or note):
			raise ValueError('"reason" and/or "note" must be specified')

		params = {}

		if reason:
			params['reason'] = reason

		if note:
			params['note'] = note

		statement = tinysql.Update('domain_bans', params, domain = domain)

		with self.query(statement) as cur:
			if cur.modified_row_count > 1:
				raise ValueError('More than one row was modified')

		return self.get_domain_ban(domain)


	def del_domain_ban(self, domain: str) -> bool:
		with self.exec_statement('del-domain-ban', {'domain': domain}) as cur:
			if cur.modified_row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.modified_row_count == 1


	def get_software_ban(self, name: str) -> Row:
		with self.exec_statement('get-software-ban', {'name': name}) as cur:
			return cur.one()


	def put_software_ban(self,
							name: str,
							reason: Optional[str] = None,
							note: Optional[str] = None) -> Row:

		params = {
			'name': name,
			'reason': reason,
			'note': note,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.exec_statement('put-software-ban', params) as cur:
			return cur.one()


	def update_software_ban(self,
						name: str,
						reason: Optional[str] = None,
						note: Optional[str] = None) -> tinysql.Row:

		if not (reason or note):
			raise ValueError('"reason" and/or "note" must be specified')

		params = {}

		if reason:
			params['reason'] = reason

		if note:
			params['note'] = note

		statement = tinysql.Update('software_bans', params, name = name)

		with self.query(statement) as cur:
			if cur.modified_row_count > 1:
				raise ValueError('More than one row was modified')

		return self.get_software_ban(name)


	def del_software_ban(self, name: str) -> bool:
		with self.exec_statement('del-software-ban', {'name': name}) as cur:
			if cur.modified_row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.modified_row_count == 1


	def get_domain_whitelist(self, domain: str) -> Row:
		with self.exec_statement('get-domain-whitelist', {'domain': domain}) as cur:
			return cur.one()


	def put_domain_whitelist(self, domain: str) -> Row:
		params = {
			'domain': domain,
			'created': datetime.now(tz = timezone.utc)
		}

		with self.exec_statement('put-domain-whitelist', params) as cur:
			return cur.one()


	def del_domain_whitelist(self, domain: str) -> bool:
		with self.exec_statement('del-domain-whitelist', {'domain': domain}) as cur:
			if cur.modified_row_count > 1:
				raise ValueError('More than one row was modified')

			return cur.modified_row_count == 1
