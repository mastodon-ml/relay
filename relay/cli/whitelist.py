import click

from . import cli, pass_state

from ..database.schema import Whitelist
from ..state import State


@cli.group("whitelist")
def cli_whitelist() -> None:
	"Manage the instance whitelist"


@cli_whitelist.command("list")
@click.pass_context
@pass_state
def cli_whitelist_list(state: State, ctx: click.Context) -> None:
	"List all the instances in the whitelist"

	click.echo("Current whitelisted domains:")

	with state.database.session() as conn:
		for row in conn.execute("SELECT * FROM whitelist").all(Whitelist):
			click.echo(f"- {row.domain}")


@cli_whitelist.command("add")
@click.argument("domain")
@pass_state
def cli_whitelist_add(state: State, domain: str) -> None:
	"Add a domain to the whitelist"

	with state.database.session() as conn:
		if conn.get_domain_whitelist(domain):
			click.echo(f"Instance already in the whitelist: {domain}")
			return

		conn.put_domain_whitelist(domain)
		click.echo(f"Instance added to the whitelist: {domain}")


@cli_whitelist.command("remove")
@click.argument("domain")
@pass_state
def cli_whitelist_remove(state: State, domain: str) -> None:
	"Remove an instance from the whitelist"

	with state.database.session() as conn:
		if not conn.del_domain_whitelist(domain):
			click.echo(f"Domain not in the whitelist: {domain}")
			return

		if conn.get_config("whitelist-enabled"):
			if conn.del_inbox(domain):
				click.echo(f"Removed inbox for domain: {domain}")

		click.echo(f"Removed domain from the whitelist: {domain}")


@cli_whitelist.command("import")
@pass_state
def cli_whitelist_import(state: State) -> None:
	"Add all current instances to the whitelist"

	with state.database.session() as conn:
		for row in conn.get_inboxes():
			if conn.get_domain_whitelist(row.domain) is not None:
				click.echo(f"Domain already in whitelist: {row.domain}")
				continue

			conn.put_domain_whitelist(row.domain)

		click.echo("Imported whitelist from inboxes")
