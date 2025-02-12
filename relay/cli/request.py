import asyncio
import click

from . import cli, pass_app

from .. import http_client as http
from ..application import Application
from ..misc import Message


@cli.group("request")
def cli_request() -> None:
	"Manage follow requests"


@cli_request.command("list")
@pass_app
def cli_request_list(app: Application) -> None:
	"List all current follow requests"

	click.echo("Follow requests:")

	with app.database.session() as conn:
		for row in conn.get_requests():
			date = row.created.strftime("%Y-%m-%d")
			click.echo(f"- [{date}] {row.domain}")


@cli_request.command("accept")
@click.argument("domain")
@pass_app
def cli_request_accept(app: Application, domain: str) -> None:
	"Accept a follow request"

	try:
		with app.database.session() as conn:
			instance = conn.put_request_response(domain, True)

	except KeyError:
		click.echo("Request not found")
		return

	message = Message.new_response(
		host = app.config.domain,
		actor = instance.actor,
		followid = instance.followid,
		accept = True
	)

	asyncio.run(http.post(instance.inbox, message, instance))

	if instance.software != "mastodon":
		message = Message.new_follow(
			host = app.config.domain,
			actor = instance.actor
		)

		asyncio.run(http.post(instance.inbox, message, instance))


@cli_request.command("deny")
@click.argument("domain")
@pass_app
def cli_request_deny(app: Application, domain: str) -> None:
	"Accept a follow request"

	try:
		with app.database.session() as conn:
			instance = conn.put_request_response(domain, False)

	except KeyError:
		click.echo("Request not found")
		return

	response = Message.new_response(
		host = app.config.domain,
		actor = instance.actor,
		followid = instance.followid,
		accept = False
	)

	asyncio.run(http.post(instance.inbox, response, instance))
