import sqlite3

from blib import Date, File
from bsql import Database

from .config import THEMES, ConfigData
from .connection import RELAY_SOFTWARE, Connection
from .schema import TABLES, VERSIONS, migrate_0

from .. import logger as logging
from ..config import Config


sqlite3.register_adapter(Date, Date.timestamp)


def get_database(config: Config, migrate: bool = True) -> Database[Connection]:
	options = {
		'connection_class': Connection,
		'pool_size': 5,
		'tables': TABLES
	}

	db: Database[Connection]

	if config.db_type == 'sqlite':
		db = Database.sqlite(config.sqlite_path, **options)

	elif config.db_type == 'postgres':
		db = Database.postgresql(
			config.pg_name,
			config.pg_host,
			config.pg_port,
			config.pg_user,
			config.pg_pass,
			**options
		)

	db.load_prepared_statements(File.from_resource('relay', 'data/statements.sql'))
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
