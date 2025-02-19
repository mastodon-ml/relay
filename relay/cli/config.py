import click

from typing import Any

from . import cli, pass_state

from ..state import State


@cli.group("config")
def cli_config() -> None:
	"Manage the relay settings stored in the database"


@cli_config.command("list")
@pass_state
def cli_config_list(state: State) -> None:
	"List the current relay config"

	click.echo("Relay Config:")

	with state.database.session() as conn:
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
@pass_state
def cli_config_set(state: State, key: str, value: Any) -> None:
	"Set a config value"

	try:
		with state.database.session() as conn:
			new_value = conn.put_config(key, value)

	except Exception:
		click.echo(f"Invalid config name: {key}")
		return

	click.echo(f"{key}: {repr(new_value)}")
