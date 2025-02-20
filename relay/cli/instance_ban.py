import click

from . import cli, pass_state

from ..state import State


# remove this in 0.4.0
@cli.group("instance", hidden = True)
def cli_instance() -> None:
	"""
		Manage instance bans (deprecated)

		Use 'activityrelay ban' instead
	"""


@cli_instance.command("list")
@pass_state
def cli_instance_list(state: State) -> None:
	"List all banned instances"

	click.echo("[DEPRECATED] Please use 'activityrelay ban list' instead")
	click.echo("Banned domains:")

	with state.database.session() as conn:
		for row in conn.get_domain_bans():
			if row.reason:
				click.echo(f"- {row.domain} ({row.reason})")

			else:
				click.echo(f"- {row.domain}")


@cli_instance.command("ban")
@click.argument("domain")
@click.option("--reason", "-r", help = "Public note about why the domain is banned")
@click.option("--note", "-n", help = "Internal note that will only be seen by admins and mods")
@pass_state
def cli_instance_ban(state: State, domain: str, reason: str, note: str) -> None:
	"Ban an instance and remove the associated inbox if it exists"

	click.echo("[DEPRECATED] Please use 'activityrelay ban add' instead")

	with state.database.session() as conn:
		if conn.get_domain_ban(domain) is not None:
			click.echo(f"Domain already banned: {domain}")
			return

		conn.put_domain_ban(domain, reason, note)
		conn.del_inbox(domain)
		click.echo(f"Banned instance: {domain}")


@cli_instance.command("unban")
@click.argument("domain")
@pass_state
def cli_instance_unban(state: State, domain: str) -> None:
	"Unban an instance"

	click.echo("[DEPRECATED] Please use 'activityrelay ban remove' instead")

	with state.database.session() as conn:
		if conn.del_domain_ban(domain) is None:
			click.echo(f"Instance wasn\"t banned: {domain}")
			return

		click.echo(f"Unbanned instance: {domain}")


@cli_instance.command("update")
@click.argument("domain")
@click.option("--reason", "-r")
@click.option("--note", "-n")
@click.pass_context
@pass_state
def cli_instance_update(
					state: State,
					ctx: click.Context,
					domain: str,
					reason: str,
					note: str) -> None:
	"Update the public reason or internal note for a domain ban"

	click.echo("[DEPRECATED] Please use 'activityrelay ban list' instead")

	if not (reason or note):
		ctx.fail("Must pass --reason or --note")

	with state.database.session() as conn:
		if not (row := conn.update_domain_ban(domain, reason, note)):
			click.echo(f"Failed to update domain ban: {domain}")
			return

		click.echo(f"Updated domain ban: {domain}")

		if row.reason:
			click.echo(f"- {row.domain} ({row.reason})")

		else:
			click.echo(f"- {row.domain}")
