from __future__ import annotations

import tinysql
import typing

from importlib.resources import files as pkgfiles

from .config import get_default_value
from .connection import Connection
from .schema import VERSIONS, migrate_0

from .. import logger as logging

if typing.TYPE_CHECKING:
	from .config import Config


def get_database(config: Config, migrate: bool = True) -> tinysql.Database:
	if config.db_type == "sqlite":
		db = tinysql.Database.sqlite(
			config.sqlite_path,
			connection_class = Connection,
			min_connections = 2,
			max_connections = 10
		)

	elif config.db_type == "postgres":
		db = tinysql.Database.postgres(
			config.pg_name,
			config.pg_host,
			config.pg_port,
			config.pg_user,
			config.pg_pass,
			connection_class = Connection
		)

	db.load_prepared_statements(pkgfiles("relay").joinpath("data", "statements.sql"))

	if not migrate:
		return db

	with db.connection() as conn:
		if 'config' not in conn.get_tables():
			logging.info("Creating database tables")
			migrate_0(conn)
			return db

		if (schema_ver := conn.get_config('schema-version')) < get_default_value('schema-version'):
			logging.info("Migrating database from version '%i'", schema_ver)

			for ver, func in VERSIONS:
				if schema_ver < ver:
					conn.begin()

					func(conn)

					conn.put_config('schema-version', ver)
					conn.commit()

		if (privkey := conn.get_config('private-key')):
			conn.app.signer = privkey

		logging.set_level(conn.get_config('log-level'))

	return db
