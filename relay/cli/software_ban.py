import asyncio
import click

from . import cli, pass_app

from .. import http_client as http
from ..application import Application
from ..misc import RELAY_SOFTWARE


@cli.group("software")
def cli_software() -> None:
	"Manage banned software"


@cli_software.command("list")
@pass_app
def cli_software_list(app: Application) -> None:
	"List all banned software"

	click.echo("Banned software:")

	with app.database.session() as conn:
		for row in conn.get_software_bans():
			if row.reason:
				click.echo(f"- {row.name} ({row.reason})")

			else:
				click.echo(f"- {row.name}")


@cli_software.command("ban")
@click.argument("name")
@click.option("--reason", "-r")
@click.option("--note", "-n")
@click.option(
	"--fetch-nodeinfo", "-f",
	is_flag = True,
	help = "Treat NAME like a domain and try to fetch the software name from nodeinfo"
)
@pass_app
def cli_software_ban(app: Application,
					name: str,
					reason: str,
					note: str,
					fetch_nodeinfo: bool) -> None:
	"Ban software. Use RELAYS for NAME to ban relays"

	with app.database.session() as conn:
		if name == "RELAYS":
			for item in RELAY_SOFTWARE:
				if conn.get_software_ban(item):
					click.echo(f"Relay already banned: {item}")
					continue

				conn.put_software_ban(item, reason or "relay", note)

			click.echo("Banned all relay software")
			return

		if fetch_nodeinfo:
			if not (nodeinfo := asyncio.run(http.fetch_nodeinfo(name))):
				click.echo(f"Failed to fetch software name from domain: {name}")
				return

			name = nodeinfo.sw_name

		if conn.get_software_ban(name):
			click.echo(f"Software already banned: {name}")
			return

		if not conn.put_software_ban(name, reason, note):
			click.echo(f"Failed to ban software: {name}")
			return

		click.echo(f"Banned software: {name}")


@cli_software.command("unban")
@click.argument("name")
@click.option("--reason", "-r")
@click.option("--note", "-n")
@click.option(
	"--fetch-nodeinfo", "-f",
	is_flag = True,
	help = "Treat NAME like a domain and try to fetch the software name from nodeinfo"
)
@pass_app
def cli_software_unban(app: Application, name: str, fetch_nodeinfo: bool) -> None:
	"Ban software. Use RELAYS for NAME to unban relays"

	with app.database.session() as conn:
		if name == "RELAYS":
			for software in RELAY_SOFTWARE:
				if not conn.del_software_ban(software):
					click.echo(f"Relay was not banned: {software}")

			click.echo("Unbanned all relay software")
			return

		if fetch_nodeinfo:
			if not (nodeinfo := asyncio.run(http.fetch_nodeinfo(name))):
				click.echo(f"Failed to fetch software name from domain: {name}")
				return

			name = nodeinfo.sw_name

		if not conn.del_software_ban(name):
			click.echo(f"Software was not banned: {name}")
			return

		click.echo(f"Unbanned software: {name}")


@cli_software.command("update")
@click.argument("name")
@click.option("--reason", "-r")
@click.option("--note", "-n")
@click.pass_context
@pass_app
def cli_software_update(
					app: Application,
					ctx: click.Context,
					name: str,
					reason: str,
					note: str) -> None:
	"Update the public reason or internal note for a software ban"

	if not (reason or note):
		ctx.fail("Must pass --reason or --note")

	with app.database.session() as conn:
		if not (row := conn.update_software_ban(name, reason, note)):
			click.echo(f"Failed to update software ban: {name}")
			return

		click.echo(f"Updated software ban: {name}")

		if row.reason:
			click.echo(f"- {row.name} ({row.reason})")

		else:
			click.echo(f"- {row.name}")
