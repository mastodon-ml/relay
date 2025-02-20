import click

from typing import Any

from . import cli, pass_state

from ..misc import RELAY_SOFTWARE
from ..state import State


@cli.group("ban")
def cli_ban() -> None:
	"Mannaged banned domains and software"


@cli_ban.command("list")
@click.option("--only-instances", "-i", is_flag = True, help = "Only list the banned instances")
@click.option("--only-software", "-s", is_flag = True, help = "Only list the banned software")
@click.option("--expanded-format", "-e", is_flag = True,
	help = "Add extra spacing for better readability")
@pass_state
def cli_ban_list(
				state: State,
				only_instances: bool,
				only_software: bool,
				expanded_format: bool) -> None:
	"List all domain and/or software bans"

	if only_instances and only_software:
		click.echo("Do not pass '--only-instances' AND '--only-software'")
		return

	template = "- {name}: {reason}"

	if expanded_format:
		template = "- {name}\n    {reason}\n"

	with state.database.session(False) as conn:
		if not only_software:
			click.echo("Banned Domains:")

			for domain in conn.get_domain_bans():
				click.echo(template.format(name = domain.domain, reason = domain.reason or "n/a"))

		if not only_instances:
			click.echo("\nBanned Software:")

			for software in conn.get_software_bans():
				click.echo(template.format(name = software.name, reason = software.reason or "n/a"))


@cli_ban.command("add")
@click.argument("name")
@click.option("--reason", help = "Publicly displayed reason for the ban")
@click.option("--note", help = "Node on the ban that can only be read by admins")
@click.option("--software", "-s", is_flag = True,
	help = "Add a software ban instad of a domain ban")
@click.option("--fetch-nodeinfo", "-n", is_flag = True,
	help = "Use 'name' as a domain to fetch nodeinfo when adding a software ban")
@pass_state
async def cli_ban_add(
			state: State,
			name: str,
			reason: str | None,
			note: str | None,
			software: bool,
			fetch_nodeinfo: bool) -> None:
	"Create a new ban"

	with state.database.session(True) as conn:
		ban: Any

		if software:
			ban = conn.get_software_ban(name)

		else:
			ban = conn.get_domain_ban(name)

		if ban:
			click.echo(f"Domain or software already banned: {name}")
			return

		if not software:
			conn.put_domain_ban(name, reason, note)
			click.echo("Banned domain")
			return

		if fetch_nodeinfo:
			async with state.client:
				if not (nodeinfo := await state.client.fetch_nodeinfo(name)):
					click.echo(f"Could not fetch nodeinfo for {repr(name)}")
					return

			name = nodeinfo.sw_name

		print(name, reason, note)
		conn.put_software_ban(name, reason, note)

	click.echo(f"Added domain or software ban: {name}")


@cli_ban.command("update")
@click.argument("name")
@click.option("--reason", help = "Publicly displayed reason for the ban")
@click.option("--note", help = "Node on the ban that can only be read by admins")
@click.option("--software", "-s", is_flag = True,
	help = "Update a software ban instad of a domain ban")
@pass_state
def cli_ban_update(
				state: State,
				name: str,
				reason: str | None,
				note: str | None,
				software: bool) -> None:
	"Update the reason or note of a ban"

	with state.database.session(True) as conn:
		if not software:
			if not conn.get_domain_ban(name):
				click.echo(f"Domain not banned: {name}")
				return

			conn.update_domain_ban(name, reason, note)

		else:
			if not conn.get_software_ban(name):
				click.echo(f"Software not banned: {name}")
				return

			conn.update_software_ban(name, reason, note)

	click.echo(f"Domain or software updated: {name}")


@cli_ban.command("remove")
@click.argument("name")
@click.option("--software", "-s", is_flag = True,
	help = "Remove a software ban instad of a domain ban")
@click.option("--fetch-nodeinfo", "-n", is_flag = True,
	help = "Use 'name' as a domain to fetch nodeinfo when adding a software ban")
@pass_state
async def cli_ban_remove(
			state: State,
			name: str,
			software: bool,
			fetch_nodeinfo: bool) -> None:
	"Remove a ban"

	result: bool

	with state.database.session(True) as conn:
		if not software:
			result = conn.del_domain_ban(name)

		else:
			if fetch_nodeinfo:
				async with state.client:
					if not (nodeinfo := await state.client.fetch_nodeinfo(name)):
						click.echo(f"Could not fetch nodeinfo for {repr(name)}")
						return

				name = nodeinfo.sw_name

			result = conn.del_software_ban(name)

		if result:
			click.echo(f"Removed domain or software ban: {name}")
			return

		click.echo(f"Domain or software ban does not exist: {name}")


@cli_ban.command("add-relays")
@click.option("--reason", help = "Publicly displayed reason for the ban")
@click.option("--note", help = "Node on the ban that can only be read by admins")
@pass_state
def cli_ban_add_relays(state: State, reason: str | None, note: str | None) -> None:
	for name in RELAY_SOFTWARE:
		cli_ban_add.callback(name, reason, note, True, False) # type: ignore[misc]


@cli_ban.command("remove-relays")
@pass_state
def cli_ban_remove_relays(state: State) -> None:
	for name in RELAY_SOFTWARE:
		cli_ban_remove.callback(name, True, False) # type: ignore[misc]
