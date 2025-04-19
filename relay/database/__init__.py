from __future__ import annotations

import sqlite3

from aputils import Signer
from blib import Date, File
from bsql import Database
from typing import TYPE_CHECKING

from .config import ConfigData
from .connection import Connection
from .schema import TABLES, VERSIONS, migrate_0

from .. import logger as logging
from ..config import Config

if TYPE_CHECKING:
	from ..state import State


sqlite3.register_adapter(Date, Date.timestamp)


def get_database(state: State, migrate: bool = True) -> Database[Connection]:
	options = {
		"connection_class": Connection,
		"pool_size": 5,
		"tables": TABLES
	}

	db: Database[Connection]

	match state.config.db_type:
		case "sqlite" | "sqlite3":
			db = Database.sqlite(state.config.sqlite_path, **options)

		case "postgres" | "postgresql":
			db = Database.postgresql(
				state.config.pg_name,
				state.config.pg_host,
				state.config.pg_port,
				state.config.pg_user,
				state.config.pg_pass,
				**options
			)

		case _:
			raise RuntimeError(f"Invalid database backend: {state.config.db_type}")

	db.load_prepared_statements(File.from_resource("relay", "data/statements.sql"))
	db.connect()

	if not migrate:
		return db

	with db.session(True) as conn:
		if "config" not in conn.get_tables():
			logging.info("Creating database tables")
			migrate_0(conn)

		elif (schema_ver := conn.get_config("schema-version")) < ConfigData.DEFAULT("schema-version"):
			logging.info("Migrating database from version '%i'", schema_ver)

			for ver, func in VERSIONS.items():
				if schema_ver < ver:
					func(conn)
					conn.put_config("schema-version", ver)
					logging.info("Updated database to %i", ver)

		logging.set_level(conn.get_config("log-level"))

	return db
