from __future__ import annotations

import typing

from bsql import Column, Row, Tables
from collections.abc import Callable
from datetime import datetime

from .config import ConfigData

if typing.TYPE_CHECKING:
	from .connection import Connection


VERSIONS: dict[int, Callable[[Connection], None]] = {}
TABLES = Tables()


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
	accepted: Column[datetime] = Column('accepted', 'boolean')
	created: Column[datetime] = Column('created', 'timestamp', nullable = False)


@TABLES.add_row
class Whitelist(Row):
	domain: Column[str] = Column(
		'domain', 'text', primary_key = True, unique = True, nullable = True)
	created: Column[datetime] = Column('created', 'timestamp')


@TABLES.add_row
class DomainBan(Row):
	table_name: str = 'domain_bans'

	domain: Column[str] = Column(
		'domain', 'text', primary_key = True, unique = True, nullable = True)
	reason: Column[str] = Column('reason', 'text')
	note: Column[str] = Column('note', 'text')
	created: Column[datetime] = Column('created', 'timestamp')


@TABLES.add_row
class SoftwareBan(Row):
	table_name: str = 'software_bans'

	name: Column[str] = Column('name', 'text', primary_key = True, unique = True, nullable = True)
	reason: Column[str] = Column('reason', 'text')
	note: Column[str] = Column('note', 'text')
	created: Column[datetime] = Column('created', 'timestamp')


@TABLES.add_row
class User(Row):
	table_name: str = 'users'

	username: Column[str] = Column(
		'username', 'text', primary_key = True, unique = True, nullable = False)
	hash: Column[str] = Column('hash', 'text', nullable = False)
	handle: Column[str] = Column('handle', 'text')
	created: Column[datetime] = Column('created', 'timestamp')


@TABLES.add_row
class Token(Row):
	table_name: str = 'tokens'

	code: Column[str] = Column('code', 'text', primary_key = True, unique = True, nullable = False)
	user: Column[str] = Column('user', 'text', nullable = False)
	created: Column[datetime] = Column('created', 'timestamp')


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
	conn.execute("ALTER TABLE inboxes ADD COLUMN accepted BOOLEAN")
	conn.execute("UPDATE inboxes SET accepted = 1")
