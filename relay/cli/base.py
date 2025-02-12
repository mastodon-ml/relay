import aputils
import click

from pathlib import Path
from shutil import copyfile

from . import cli, pass_app

from .. import logger as logging
from ..application import Application
from ..compat import RelayConfig, RelayDatabase
from ..config import Config
from ..database import TABLES, get_database
from ..misc import IS_DOCKER, RELAY_SOFTWARE
from ..views import ROUTES


def check_alphanumeric(text: str) -> str:
	if not text.isalnum():
		raise click.BadParameter("String not alphanumeric")

	return text


@cli.command("convert")
@click.option("--old-config", "-o", help = "Path to the config file to convert from")
@pass_app
def cli_convert(app: Application, old_config: str) -> None:
	"Convert an old config and jsonld database to the new format."

	old_config = str(Path(old_config).expanduser().resolve()) if old_config else str(app.config.path)
	backup = app.config.path.parent.joinpath(f"{app.config.path.stem}.backup.yaml")

	if str(old_config) == str(app.config.path) and not backup.exists():
		logging.info("Created backup config @ %s", backup)
		copyfile(app.config.path, backup)

	config = RelayConfig(old_config)
	config.load()

	database = RelayDatabase(config)
	database.load()

	app.config.set("listen", config["listen"])
	app.config.set("port", config["port"])
	app.config.set("workers", config["workers"])
	app.config.set("sq_path", config["db"].replace("jsonld", "sqlite3"))
	app.config.set("domain", config["host"])
	app.config.save()

	with get_database(app.config) as db:
		with db.session(True) as conn:
			conn.put_config("private-key", database["private-key"])
			conn.put_config("note", config["note"])
			conn.put_config("whitelist-enabled", config.get("whitelist-enabled", False))

			with click.progressbar(
				database["relay-list"].values(),
				label = "Inboxes".ljust(15),
				width = 0
			) as inboxes:
				for inbox in inboxes:
					match inbox["software"]:
						case "akkoma" | "pleroma":
							inbox["actor"] = f"https://{inbox['domain']}/relay"

						case "mastodon":
							inbox["actor"] = f"https://{inbox['domain']}/actor"

						case _:
							inbox["actor"] = None

					conn.put_inbox(
						inbox["domain"],
						inbox["inbox"],
						actor = inbox["actor"],
						followid = inbox["followid"],
						software = inbox["software"]
					)

			with click.progressbar(
				config.get("blocked_software", []),
				label = "Banned software".ljust(15),
				width = 0
			) as banned_software:

				for software in banned_software:
					conn.put_software_ban(
						software,
						reason = "relay" if software in RELAY_SOFTWARE else None
					)

			with click.progressbar(
				config.get("blocked_instances", []),
				label = "Banned domains".ljust(15),
				width = 0
			) as banned_software:

				for domain in banned_software:
					conn.put_domain_ban(domain)

			with click.progressbar(
				config.get("whitelist", []),
				label = "Whitelist".ljust(15),
				width = 0
			) as whitelist:

				for instance in whitelist:
					conn.put_domain_whitelist(instance)

	click.echo("Finished converting old config and database :3")


@cli.command("db-maintenance")
@pass_app
def cli_db_maintenance(app: Application) -> None:
	"Perform maintenance tasks on the database"

	if app.config.db_type == "postgres":
		return

	with app.database.session(False) as s:
		with s.transaction():
			s.fix_timestamps()

		with s.execute("VACUUM"):
			pass


@cli.command("edit-config")
@click.option("--editor", "-e", help = "Text editor to use")
@pass_app
def cli_editconfig(app: Application, editor: str) -> None:
	"Edit the config file"

	click.edit(
		editor = editor,
		filename = str(app.config.path)
	)


@cli.command("run")
@click.option("--dev", "-d", is_flag=True, help="Enable developer mode")
@pass_app
def cli_run(app: Application, dev: bool = False) -> None:
	"Run the relay"

	if app.config.domain.endswith("example.com") or app.signer is None:
		if not IS_DOCKER:
			click.echo("Relay is not set up. Please run \"activityrelay setup\"")

			return

		cli_setup.callback() # type: ignore
		return

	for method, path, handler in ROUTES:
		app.router.add_route(method, path, handler)

	app["dev"] = dev
	app.run()


@cli.command("setup")
@click.option("--skip-questions", "-s", is_flag = True,
	help = "Assume the config file is correct and just setup the database")
@pass_app
def cli_setup(app: Application, skip_questions: bool) -> None:
	"Generate a new config and create the database"

	if app.signer is not None:
		if not click.prompt("The database is already setup. Are you sure you want to continue?"):
			return

	if skip_questions and app.config.domain.endswith("example.com"):
		click.echo("You cannot skip the questions if the relay is not configured yet")
		return

	if not skip_questions:
		while True:
			app.config.domain = click.prompt(
				"What domain will the relay be hosted on?",
				default = app.config.domain
			)

			if not app.config.domain.endswith("example.com"):
				break

			click.echo("The domain must not end with \"example.com\"")

		if not IS_DOCKER:
			app.config.listen = click.prompt(
				"Which address should the relay listen on?",
				default = app.config.listen
			)

			app.config.port = click.prompt(
				"What TCP port should the relay listen on?",
				default = app.config.port,
				type = int
			)

		app.config.db_type = click.prompt(
			"Which database backend will be used?",
			default = app.config.db_type,
			type = click.Choice(["postgres", "sqlite"], case_sensitive = False)
		)

		if app.config.db_type == "sqlite" and not IS_DOCKER:
			app.config.sq_path = click.prompt(
				"Where should the database be stored?",
				default = app.config.sq_path
			)

		elif app.config.db_type == "postgres":
			config_postgresql(app.config)

		app.config.ca_type = click.prompt(
			"Which caching backend?",
			default = app.config.ca_type,
			type = click.Choice(["database", "redis"], case_sensitive = False)
		)

		if app.config.ca_type == "redis":
			app.config.rd_host = click.prompt(
				"What IP address, hostname, or unix socket does the server listen on?",
				default = app.config.rd_host
			)

			app.config.rd_port = click.prompt(
				"What port does the server listen on?",
				default = app.config.rd_port,
				type = int
			)

			app.config.rd_user = click.prompt(
				"Which user will authenticate with the server",
				default = app.config.rd_user
			)

			app.config.rd_pass = click.prompt(
				"User password",
				hide_input = True,
				show_default = False,
				default = app.config.rd_pass or ""
			) or None

			app.config.rd_database = click.prompt(
				"Which database number to use?",
				default = app.config.rd_database,
				type = int
			)

			app.config.rd_prefix = click.prompt(
				"What text should each cache key be prefixed with?",
				default = app.config.rd_database,
				type = check_alphanumeric
			)

		app.config.save()

	config = {
		"private-key": aputils.Signer.new("n/a").export()
	}

	with app.database.session() as conn:
		for key, value in config.items():
			conn.put_config(key, value)

	if IS_DOCKER:
		click.echo("Relay all setup! Start the container to run the relay.")
		return

	if click.confirm("Relay all setup! Would you like to run it now?"):
		cli_run.callback() # type: ignore


@cli.command("switch-backend")
@pass_app
def cli_switchbackend(app: Application) -> None:
	"""
		Copy the database from one backend to the other

		Be sure to set the database type to the backend you want to convert from. For instance, set
		the database type to `sqlite`, fill out the connection details for postgresql, and the
		data from the sqlite database will be copied to the postgresql database. This only works if
		the database in postgresql already exists.
	"""

	config = Config(app.config.path, load = True)
	config.db_type = "sqlite" if config.db_type == "postgres" else "postgres"

	if config.db_type == "postgres":
		if click.confirm("Setup PostgreSQL configuration?"):
			config_postgresql(config)

		order = ("SQLite", "PostgreSQL")
		click.pause("Make sure the database and user already exist before continuing")

	else:
		order = ("PostgreSQL", "SQLite")

	click.echo(f"About to convert from {order[0]} to {order[1]}...")
	database = get_database(config, migrate = False)

	with database.session(True) as new, app.database.session(False) as old:
		if click.confirm("All tables in the destination database will be dropped. Continue?"):
			new.drop_tables()

		new.create_tables()

		for table in TABLES.keys():
			for row in old.execute(f"SELECT * FROM {table}"):
				new.insert(table, row).close()

		config.save()
		click.echo("Done!")


def config_postgresql(config: Config) -> None:
	config.pg_name = click.prompt(
		"What is the name of the database?",
		default = config.pg_name
	)

	config.pg_host = click.prompt(
		"What IP address, hostname, or unix socket does the server listen on?",
		default = config.pg_host,
	)

	config.pg_port = click.prompt(
		"What port does the server listen on?",
		default = config.pg_port,
		type = int
	)

	config.pg_user = click.prompt(
		"Which user will authenticate with the server?",
		default = config.pg_user
	)

	config.pg_pass = click.prompt(
		"User password",
		hide_input = True,
		show_default = False,
		default = config.pg_pass or ""
	) or None
