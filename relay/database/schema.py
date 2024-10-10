from __future__ import annotations

from blib import Date
from bsql import Column, Row, Tables
from collections.abc import Callable
from copy import deepcopy
from datetime import timezone
from typing import TYPE_CHECKING, Any

from .config import ConfigData

if TYPE_CHECKING:
	from .connection import Connection


VERSIONS: dict[int, Callable[[Connection], None]] = {}
TABLES = Tables()


def deserialize_timestamp(value: Any) -> Date:
	try:
		date = Date.parse(value)

	except ValueError:
		date = Date.fromisoformat(value)

	if date.tzinfo is None:
		date = date.replace(tzinfo = timezone.utc)

	return date


@TABLES.add_row
class Config(Row):
	key: Column[str] = Column('key', 'text', primary_key = True, unique = True, nullable = False)
	value: Column[str] = Column('value', 'text')
	type: Column[str] = Column('type', 'text', default = 'str')


@TABLES.add_row
class Instance(Row):
	table_name: str = 'inboxes'


	domain: Column[str] = Column(
		'domain', 'text', primary_key = True, unique = True, nullable = False)
	actor: Column[str] = Column('actor', 'text', unique = True)
	inbox: Column[str] = Column('inbox', 'text', unique = True, nullable = False)
	followid: Column[str] = Column('followid', 'text')
	software: Column[str] = Column('software', 'text')
	accepted: Column[Date] = Column('accepted', 'boolean')
	created: Column[Date] = Column(
		'created', 'timestamp', nullable = False, deserializer = deserialize_timestamp)


@TABLES.add_row
class Whitelist(Row):
	domain: Column[str] = Column(
		'domain', 'text', primary_key = True, unique = True, nullable = True)
	created: Column[Date] = Column(
		'created', 'timestamp', nullable = False, deserializer = deserialize_timestamp)


@TABLES.add_row
class DomainBan(Row):
	table_name: str = 'domain_bans'


	domain: Column[str] = Column(
		'domain', 'text', primary_key = True, unique = True, nullable = True)
	reason: Column[str] = Column('reason', 'text')
	note: Column[str] = Column('note', 'text')
	created: Column[Date] = Column(
		'created', 'timestamp', nullable = False, deserializer = deserialize_timestamp)


@TABLES.add_row
class SoftwareBan(Row):
	table_name: str = 'software_bans'


	name: Column[str] = Column('name', 'text', primary_key = True, unique = True, nullable = True)
	reason: Column[str] = Column('reason', 'text')
	note: Column[str] = Column('note', 'text')
	created: Column[Date] = Column(
		'created', 'timestamp', nullable = False, deserializer = deserialize_timestamp)


@TABLES.add_row
class User(Row):
	table_name: str = 'users'


	username: Column[str] = Column(
		'username', 'text', primary_key = True, unique = True, nullable = False)
	hash: Column[str] = Column('hash', 'text', nullable = False)
	handle: Column[str] = Column('handle', 'text')
	created: Column[Date] = Column(
		'created', 'timestamp', nullable = False, deserializer = deserialize_timestamp)


@TABLES.add_row
class App(Row):
	table_name: str = 'apps'


	client_id: Column[str] = Column(
		'client_id', 'text', primary_key = True, unique = True, nullable = False)
	client_secret: Column[str] = Column('client_secret', 'text', nullable = False)
	name: Column[str] = Column('name', 'text')
	website: Column[str] = Column('website', 'text')
	redirect_uri: Column[str] = Column('redirect_uri', 'text', nullable = False)
	token: Column[str | None] = Column('token', 'text')
	auth_code: Column[str | None] = Column('auth_code', 'text')
	user: Column[str | None] = Column('user', 'text')
	created: Column[Date] = Column(
		'created', 'timestamp', nullable = False, deserializer = deserialize_timestamp)
	accessed: Column[Date] = Column(
		'accessed', 'timestamp', nullable = False, deserializer = deserialize_timestamp)


	def get_api_data(self, include_token: bool = False) -> dict[str, Any]:
		data = deepcopy(self)
		data.pop('user')
		data.pop('auth_code')

		if not include_token:
			data.pop('token')

		return data


def migration(func: Callable[[Connection], None]) -> Callable[[Connection], None]:
	ver = int(func.__name__.replace('migrate_', ''))
	VERSIONS[ver] = func
	return func


def migrate_0(conn: Connection) -> None:
	conn.create_tables()
	conn.put_config('schema-version', ConfigData.DEFAULT('schema-version'))


@migration
def migrate_20240206(conn: Connection) -> None:
	conn.create_tables()


@migration
def migrate_20240310(conn: Connection) -> None:
	conn.execute('ALTER TABLE "inboxes" ADD COLUMN "accepted" BOOLEAN').close()
	conn.execute('UPDATE "inboxes" SET "accepted" = true').close()


@migration
def migrate_20240625(conn: Connection) -> None:
	conn.create_tables()
	conn.execute('DROP TABLE "tokens"').close()
