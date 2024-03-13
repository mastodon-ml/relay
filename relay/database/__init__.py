from __future__ import annotations

import bsql
import typing

from .config import THEMES, ConfigData
from .connection import RELAY_SOFTWARE, Connection
from .schema import TABLES, VERSIONS, migrate_0

from .. import logger as logging
from ..misc import get_resource

if typing.TYPE_CHECKING:
	from ..config import Config


def get_database(config: Config, migrate: bool = True) -> bsql.Database:
	options = {
		'connection_class': Connection,
		'pool_size': 5,
		'tables': TABLES
	}

	if config.db_type == 'sqlite':
		db = bsql.Database.sqlite(config.sqlite_path, **options)

	elif config.db_type == 'postgres':
		db = bsql.Database.postgresql(
			config.pg_name,
			config.pg_host,
			config.pg_port,
			config.pg_user,
			config.pg_pass,
			**options
		)

	db.load_prepared_statements(get_resource('data/statements.sql'))
	db.connect()

	if not migrate:
		return db

	with db.session(True) as conn:
		if 'config' not in conn.get_tables():
			logging.info("Creating database tables")
			migrate_0(conn)
			return db

		if (schema_ver := conn.get_config('schema-version')) < ConfigData.DEFAULT('schema-version'):
			logging.info("Migrating database from version '%i'", schema_ver)

			for ver, func in VERSIONS.items():
				if schema_ver < ver:
					func(conn)
					conn.put_config('schema-version', ver)
					logging.info("Updated database to %i", ver)

		if (privkey := conn.get_config('private-key')):
			conn.app.signer = privkey

		logging.set_level(conn.get_config('log-level'))

	return db
