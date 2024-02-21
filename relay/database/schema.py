from __future__ import annotations

import typing

from bsql import Column, Connection, Table, Tables

from .config import get_default_value

if typing.TYPE_CHECKING:
	from collections.abc import Callable


VERSIONS: dict[int, Callable] = {}
TABLES: Tables = Tables(
	Table(
		'config',
		Column('key', 'text', primary_key = True, unique = True, nullable = False),
		Column('value', 'text'),
		Column('type', 'text', default = 'str')
	),
	Table(
		'inboxes',
		Column('domain', 'text', primary_key = True, unique = True, nullable = False),
		Column('actor', 'text', unique = True),
		Column('inbox', 'text', unique = True, nullable = False),
		Column('followid', 'text'),
		Column('software', 'text'),
		Column('created', 'timestamp', nullable = False)
	),
	Table(
		'whitelist',
		Column('domain', 'text', primary_key = True, unique = True, nullable = True),
		Column('created', 'timestamp')
	),
	Table(
		'domain_bans',
		Column('domain', 'text', primary_key = True, unique = True, nullable = True),
		Column('reason', 'text'),
		Column('note', 'text'),
		Column('created', 'timestamp', nullable = False)
	),
	Table(
		'software_bans',
		Column('name', 'text', primary_key = True, unique = True, nullable = True),
		Column('reason', 'text'),
		Column('note', 'text'),
		Column('created', 'timestamp', nullable = False)
	),
	Table(
		'users',
		Column('username', 'text', primary_key = True, unique = True, nullable = False),
		Column('hash', 'text', nullable = False),
		Column('handle', 'text'),
		Column('created', 'timestamp', nullable = False)
	),
	Table(
		'tokens',
		Column('code', 'text', primary_key = True, unique = True, nullable = False),
		Column('user', 'text', nullable = False),
		Column('created', 'timestmap', nullable = False)
	)
)


def migration(func: Callable) -> Callable:
	ver = int(func.__name__.replace('migrate_', ''))
	VERSIONS[ver] = func
	return func


def migrate_0(conn: Connection) -> None:
	conn.create_tables()
	conn.put_config('schema-version', get_default_value('schema-version'))


@migration
def migrate_20240206(conn: Connection) -> None:
	conn.create_tables()
