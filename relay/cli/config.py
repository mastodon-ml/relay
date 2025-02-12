import click

from typing import Any

from . import cli, pass_app

from ..application import Application


@cli.group("config")
def cli_config() -> None:
	"Manage the relay settings stored in the database"


@cli_config.command("list")
@pass_app
def cli_config_list(app: Application) -> None:
	"List the current relay config"

	click.echo("Relay Config:")

	with app.database.session() as conn:
		config = conn.get_config_all()

		for key, value in config.to_dict().items():
			if key in type(config).SYSTEM_KEYS():
				continue

			if key == "log-level":
				value = value.name

			key_str = f"{key}:".ljust(20)
			click.echo(f"- {key_str} {repr(value)}")


@cli_config.command("set")
@click.argument("key")
@click.argument("value")
@pass_app
def cli_config_set(app: Application, key: str, value: Any) -> None:
	"Set a config value"

	try:
		with app.database.session() as conn:
			new_value = conn.put_config(key, value)

	except Exception:
		click.echo(f"Invalid config name: {key}")
		return

	click.echo(f"{key}: {repr(new_value)}")
