import click

from . import cli, pass_state

from ..misc import RELAY_SOFTWARE
from ..state import State


# remove this in 0.4.0
@cli.group("software", hidden = True)
def cli_software() -> None:
	"""
		Manage software bans (deprecated)

		Use 'activityrelay ban' instead
	"""


@cli_software.command("list")
@pass_state
def cli_software_list(state: State) -> None:
	"List all banned software"

	click.echo("[DEPRECATED] Please use 'activityrelay ban list' instead")
	click.echo("Banned software:")

	with state.database.session() as conn:
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
@pass_state
async def cli_software_ban(state: State,
					name: str,
					reason: str,
					note: str,
					fetch_nodeinfo: bool) -> None:
	"Ban software. Use RELAYS for NAME to ban relays"

	click.echo("[DEPRECATED] Please use 'activityrelay ban add --software' instead")

	with state.database.session() as conn:
		if name == "RELAYS":
			for item in RELAY_SOFTWARE:
				if conn.get_software_ban(item):
					click.echo(f"Relay already banned: {item}")
					continue

				conn.put_software_ban(item, reason or "relay", note)

			click.echo("Banned all relay software")
			return

		if fetch_nodeinfo:
			async with state.client:
				nodeinfo = await state.client.fetch_nodeinfo(name)

			if not nodeinfo:
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
@pass_state
async def cli_software_unban(state: State, name: str, fetch_nodeinfo: bool) -> None:
	"Ban software. Use RELAYS for NAME to unban relays"

	click.echo("[DEPRECATED] Please use 'activityrelay ban remove --software' instead")

	with state.database.session() as conn:
		if name == "RELAYS":
			for software in RELAY_SOFTWARE:
				if not conn.del_software_ban(software):
					click.echo(f"Relay was not banned: {software}")

			click.echo("Unbanned all relay software")
			return

		if fetch_nodeinfo:
			async with state.client:
				nodeinfo = await state.client.fetch_nodeinfo(name)

			if not nodeinfo:
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
@pass_state
def cli_software_update(
					state: State,
					ctx: click.Context,
					name: str,
					reason: str,
					note: str) -> None:
	"Update the public reason or internal note for a software ban"

	click.echo("[DEPRECATED] Please use 'activityrelay ban update --software' instead")

	if not (reason or note):
		ctx.fail("Must pass --reason or --note")

	with state.database.session() as conn:
		if not (row := conn.update_software_ban(name, reason, note)):
			click.echo(f"Failed to update software ban: {name}")
			return

		click.echo(f"Updated software ban: {name}")

		if row.reason:
			click.echo(f"- {row.name} ({row.reason})")

		else:
			click.echo(f"- {row.name}")
