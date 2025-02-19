import click

from . import cli, pass_state

from ..misc import Message
from ..state import State


@cli.group("request")
def cli_request() -> None:
	"Manage follow requests"


@cli_request.command("list")
@pass_state
def cli_request_list(state: State) -> None:
	"List all current follow requests"

	click.echo("Follow requests:")

	with state.database.session() as conn:
		for row in conn.get_requests():
			date = row.created.strftime("%Y-%m-%d")
			click.echo(f"- [{date}] {row.domain}")


@cli_request.command("accept")
@click.argument("domain")
@pass_state
async def cli_request_accept(state: State, domain: str) -> None:
	"Accept a follow request"

	try:
		with state.database.session() as conn:
			instance = conn.put_request_response(domain, True)

	except KeyError:
		click.echo("Request not found")
		return

	response = Message.new_response(
		host = state.config.domain,
		actor = instance.actor,
		followid = instance.followid,
		accept = True
	)

	async with state.client:
		await state.client.post(instance.inbox, response, instance)

		if instance.software != "mastodon":
			follow = Message.new_follow(
				host = state.config.domain,
				actor = instance.actor
			)

			await state.client.post(instance.inbox, follow, instance)


@cli_request.command("deny")
@click.argument("domain")
@pass_state
async def cli_request_deny(state: State, domain: str) -> None:
	"Accept a follow request"

	try:
		with state.database.session() as conn:
			instance = conn.put_request_response(domain, False)

	except KeyError:
		click.echo("Request not found")
		return

	response = Message.new_response(
		host = state.config.domain,
		actor = instance.actor,
		followid = instance.followid,
		accept = False
	)

	async with state.client:
		await state.client.post(instance.inbox, response, instance)
