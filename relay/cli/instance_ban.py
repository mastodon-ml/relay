import click

from . import cli, pass_app

from ..application import Application


@cli.group("instance")
def cli_instance() -> None:
	"Manage instance bans"


@cli_instance.command("list")
@pass_app
def cli_instance_list(app: Application) -> None:
	"List all banned instances"

	click.echo("Banned domains:")

	with app.database.session() as conn:
		for row in conn.get_domain_bans():
			if row.reason:
				click.echo(f"- {row.domain} ({row.reason})")

			else:
				click.echo(f"- {row.domain}")


@cli_instance.command("ban")
@click.argument("domain")
@click.option("--reason", "-r", help = "Public note about why the domain is banned")
@click.option("--note", "-n", help = "Internal note that will only be seen by admins and mods")
@pass_app
def cli_instance_ban(app: Application, domain: str, reason: str, note: str) -> None:
	"Ban an instance and remove the associated inbox if it exists"

	with app.database.session() as conn:
		if conn.get_domain_ban(domain) is not None:
			click.echo(f"Domain already banned: {domain}")
			return

		conn.put_domain_ban(domain, reason, note)
		conn.del_inbox(domain)
		click.echo(f"Banned instance: {domain}")


@cli_instance.command("unban")
@click.argument("domain")
@pass_app
def cli_instance_unban(app: Application, domain: str) -> None:
	"Unban an instance"

	with app.database.session() as conn:
		if conn.del_domain_ban(domain) is None:
			click.echo(f"Instance wasn\"t banned: {domain}")
			return

		click.echo(f"Unbanned instance: {domain}")


@cli_instance.command("update")
@click.argument("domain")
@click.option("--reason", "-r")
@click.option("--note", "-n")
@click.pass_context
@pass_app
def cli_instance_update(
					app: Application,
					ctx: click.Context,
					domain: str,
					reason: str,
					note: str) -> None:
	"Update the public reason or internal note for a domain ban"

	if not (reason or note):
		ctx.fail("Must pass --reason or --note")

	with app.database.session() as conn:
		if not (row := conn.update_domain_ban(domain, reason, note)):
			click.echo(f"Failed to update domain ban: {domain}")
			return

		click.echo(f"Updated domain ban: {domain}")

		if row.reason:
			click.echo(f"- {row.domain} ({row.reason})")

		else:
			click.echo(f"- {row.domain}")
