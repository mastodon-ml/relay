import click

from . import cli, pass_state

from ..state import State


@cli.group("user")
def cli_user() -> None:
	"Manage local users"


@cli_user.command("list")
@pass_state
def cli_user_list(state: State) -> None:
	"List all local users"

	click.echo("Users:")

	with state.database.session() as conn:
		for row in conn.get_users():
			click.echo(f"- {row.username}")


@cli_user.command("create")
@click.argument("username")
@click.argument("handle", required = False)
@pass_state
def cli_user_create(state: State, username: str, handle: str) -> None:
	"Create a new local user"

	with state.database.session() as conn:
		if conn.get_user(username) is not None:
			click.echo(f"User already exists: {username}")
			return

		while True:
			if not (password := click.prompt("New password", hide_input = True)):
				click.echo("No password provided")
				continue

			if password != click.prompt("New password again", hide_input = True):
				click.echo("Passwords do not match")
				continue

			break

		conn.put_user(username, password, handle)

	click.echo(f"Created user {username}")


@cli_user.command("delete")
@click.argument("username")
@pass_state
def cli_user_delete(state: State, username: str) -> None:
	"Delete a local user"

	with state.database.session() as conn:
		if conn.get_user(username) is None:
			click.echo(f"User does not exist: {username}")
			return

		conn.del_user(username)

	click.echo(f"Deleted user {username}")
