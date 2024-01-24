from __future__ import annotations

import typing

from tinysql import Column, Connection, Table

from .config import get_default_value

if typing.TYPE_CHECKING:
	from collections.abc import Callable


VERSIONS: list[Callable] = []
TABLES: list[Table] = [
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
		'instance_bans',
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
	)
]


def version(func: Callable) -> Callable:
	ver = int(func.replace('migrate_', ''))
	VERSIONS[ver] = func
	return func


def migrate_0(conn: Connection) -> None:
	conn.create_tables(TABLES)
	conn.put_config('schema-version', get_default_value('schema-version'))
