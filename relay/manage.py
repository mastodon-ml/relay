from __future__ import annotations

import Crypto
import asyncio
import click
import platform
import typing

from urllib.parse import urlparse

from . import misc, __version__
from . import http_client as http
from .application import Application
from .config import RELAY_SOFTWARE

if typing.TYPE_CHECKING:
	from typing import Any


# pylint: disable=unsubscriptable-object,unsupported-assignment-operation


app = None
CONFIG_IGNORE = {'blocked_software', 'blocked_instances', 'whitelist'}


@click.group('cli', context_settings={'show_default': True}, invoke_without_command=True)
@click.option('--config', '-c', default='relay.yaml', help='path to the relay\'s config')
@click.version_option(version=__version__, prog_name='ActivityRelay')
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
	global app
	app = Application(config)

	if not ctx.invoked_subcommand:
		if app.config.host.endswith('example.com'):
			cli_setup.callback()

		else:
			cli_run.callback()


@cli.command('setup')
def cli_setup() -> None:
	'Generate a new config'

	while True:
		app.config.host = click.prompt(
			'What domain will the relay be hosted on?',
			default = app.config.host
		)

		if not app.config.host.endswith('example.com'):
			break

		click.echo('The domain must not be example.com')

	if not app.config.is_docker:
		app.config.listen = click.prompt(
			'Which address should the relay listen on?',
			default = app.config.listen
		)

		while True:
			app.config.port = click.prompt(
				'What TCP port should the relay listen on?',
				default = app.config.port,
				type = int
			)

			break

	app.config.save()

	if not app.config.is_docker and click.confirm('Relay all setup! Would you like to run it now?'):
		cli_run.callback()


@cli.command('run')
def cli_run() -> None:
	'Run the relay'

	if app.config.host.endswith('example.com'):
		click.echo(
			'Relay is not set up. Please edit your relay config or run "activityrelay setup".'
		)

		return

	vers_split = platform.python_version().split('.')
	pip_command = 'pip3 uninstall pycrypto && pip3 install pycryptodome'

	if Crypto.__version__ == '2.6.1':
		if int(vers_split[1]) > 7:
			click.echo(
				'Error: PyCrypto is broken on Python 3.8+. Please replace it with pycryptodome ' +
				'before running again. Exiting...'
			)

			click.echo(pip_command)
			return

		click.echo('Warning: PyCrypto is old and should be replaced with pycryptodome')
		click.echo(pip_command)
		return

	if not misc.check_open_port(app.config.listen, app.config.port):
		click.echo(f'Error: A server is already running on port {app.config.port}')
		return

	app.run()


@cli.group('config')
def cli_config() -> None:
	'Manage the relay config'


@cli_config.command('list')
def cli_config_list() -> None:
	'List the current relay config'

	click.echo('Relay Config:')

	for key, value in app.config.items():
		if key not in CONFIG_IGNORE:
			key = f'{key}:'.ljust(20)
			click.echo(f'- {key} {value}')


@cli_config.command('set')
@click.argument('key')
@click.argument('value')
def cli_config_set(key: str, value: Any) -> None:
	'Set a config value'

	app.config[key] = value
	app.config.save()

	print(f'{key}: {app.config[key]}')


@cli.group('inbox')
def cli_inbox() -> None:
	'Manage the inboxes in the database'


@cli_inbox.command('list')
def cli_inbox_list() -> None:
	'List the connected instances or relays'

	click.echo('Connected to the following instances or relays:')

	for inbox in app.database.inboxes:
		click.echo(f'- {inbox}')


@cli_inbox.command('follow')
@click.argument('actor')
def cli_inbox_follow(actor: str) -> None:
	'Follow an actor (Relay must be running)'

	if app.config.is_banned(actor):
		click.echo(f'Error: Refusing to follow banned actor: {actor}')
		return

	if not actor.startswith('http'):
		domain = actor
		actor = f'https://{actor}/actor'

	else:
		domain = urlparse(actor).hostname

	try:
		inbox_data = app.database['relay-list'][domain]
		inbox = inbox_data['inbox']

	except KeyError:
		actor_data = asyncio.run(http.get(app.database, actor, sign_headers=True))

		if not actor_data:
			click.echo(f'Failed to fetch actor: {actor}')
			return

		inbox = actor_data.shared_inbox

	message = misc.Message.new_follow(
		host = app.config.host,
		actor = actor
	)

	asyncio.run(http.post(app.database, inbox, message))
	click.echo(f'Sent follow message to actor: {actor}')


@cli_inbox.command('unfollow')
@click.argument('actor')
def cli_inbox_unfollow(actor: str) -> None:
	'Unfollow an actor (Relay must be running)'

	if not actor.startswith('http'):
		domain = actor
		actor = f'https://{actor}/actor'

	else:
		domain = urlparse(actor).hostname

	try:
		inbox_data = app.database['relay-list'][domain]
		inbox = inbox_data['inbox']
		message = misc.Message.new_unfollow(
			host = app.config.host,
			actor = actor,
			follow = inbox_data['followid']
		)

	except KeyError:
		actor_data = asyncio.run(http.get(app.database, actor, sign_headers=True))
		inbox = actor_data.shared_inbox
		message = misc.Message.new_unfollow(
			host = app.config.host,
			actor = actor,
			follow = {
				'type': 'Follow',
				'object': actor,
				'actor': f'https://{app.config.host}/actor'
			}
		)

	asyncio.run(http.post(app.database, inbox, message))
	click.echo(f'Sent unfollow message to: {actor}')


@cli_inbox.command('add')
@click.argument('inbox')
def cli_inbox_add(inbox: str) -> None:
	'Add an inbox to the database'

	if not inbox.startswith('http'):
		inbox = f'https://{inbox}/inbox'

	if app.config.is_banned(inbox):
		click.echo(f'Error: Refusing to add banned inbox: {inbox}')
		return

	if app.database.get_inbox(inbox):
		click.echo(f'Error: Inbox already in database: {inbox}')
		return

	app.database.add_inbox(inbox)
	app.database.save()

	click.echo(f'Added inbox to the database: {inbox}')


@cli_inbox.command('remove')
@click.argument('inbox')
def cli_inbox_remove(inbox: str) -> None:
	'Remove an inbox from the database'

	try:
		dbinbox = app.database.get_inbox(inbox, fail=True)

	except KeyError:
		click.echo(f'Error: Inbox does not exist: {inbox}')
		return

	app.database.del_inbox(dbinbox['domain'])
	app.database.save()

	click.echo(f'Removed inbox from the database: {inbox}')


@cli.group('instance')
def cli_instance() -> None:
	'Manage instance bans'


@cli_instance.command('list')
def cli_instance_list() -> None:
	'List all banned instances'

	click.echo('Banned instances or relays:')

	for domain in app.config.blocked_instances:
		click.echo(f'- {domain}')


@cli_instance.command('ban')
@click.argument('target')
def cli_instance_ban(target: str) -> None:
	'Ban an instance and remove the associated inbox if it exists'

	if target.startswith('http'):
		target = urlparse(target).hostname

	if app.config.ban_instance(target):
		app.config.save()

		if app.database.del_inbox(target):
			app.database.save()

		click.echo(f'Banned instance: {target}')
		return

	click.echo(f'Instance already banned: {target}')


@cli_instance.command('unban')
@click.argument('target')
def cli_instance_unban(target: str) -> None:
	'Unban an instance'

	if app.config.unban_instance(target):
		app.config.save()

		click.echo(f'Unbanned instance: {target}')
		return

	click.echo(f'Instance wasn\'t banned: {target}')


@cli.group('software')
def cli_software() -> None:
	'Manage banned software'


@cli_software.command('list')
def cli_software_list() -> None:
	'List all banned software'

	click.echo('Banned software:')

	for software in app.config.blocked_software:
		click.echo(f'- {software}')


@cli_software.command('ban')
@click.option(
	'--fetch-nodeinfo/--ignore-nodeinfo', '-f', 'fetch_nodeinfo', default = False,
	help = 'Treat NAME like a domain and try to fet the software name from nodeinfo'
)
@click.argument('name')
def cli_software_ban(name: str, fetch_nodeinfo: bool) -> None:
	'Ban software. Use RELAYS for NAME to ban relays'

	if name == 'RELAYS':
		for software in RELAY_SOFTWARE:
			app.config.ban_software(software)

		app.config.save()
		click.echo('Banned all relay software')
		return

	if fetch_nodeinfo:
		nodeinfo = asyncio.run(http.fetch_nodeinfo(app.database, name))

		if not nodeinfo:
			click.echo(f'Failed to fetch software name from domain: {name}')

		name = nodeinfo.sw_name

	if app.config.ban_software(name):
		app.config.save()
		click.echo(f'Banned software: {name}')
		return

	click.echo(f'Software already banned: {name}')


@cli_software.command('unban')
@click.option(
	'--fetch-nodeinfo/--ignore-nodeinfo', '-f', 'fetch_nodeinfo', default = False,
	help = 'Treat NAME like a domain and try to fet the software name from nodeinfo'
)
@click.argument('name')
def cli_software_unban(name: str, fetch_nodeinfo: bool) -> None:
	'Ban software. Use RELAYS for NAME to unban relays'

	if name == 'RELAYS':
		for software in RELAY_SOFTWARE:
			app.config.unban_software(software)

		app.config.save()
		click.echo('Unbanned all relay software')
		return

	if fetch_nodeinfo:
		nodeinfo = asyncio.run(http.fetch_nodeinfo(app.database, name))

		if not nodeinfo:
			click.echo(f'Failed to fetch software name from domain: {name}')

		name = nodeinfo.sw_name

	if app.config.unban_software(name):
		app.config.save()
		click.echo(f'Unbanned software: {name}')
		return

	click.echo(f'Software wasn\'t banned: {name}')


@cli.group('whitelist')
def cli_whitelist() -> None:
	'Manage the instance whitelist'


@cli_whitelist.command('list')
def cli_whitelist_list() -> None:
	'List all the instances in the whitelist'

	click.echo('Current whitelisted domains')

	for domain in app.config.whitelist:
		click.echo(f'- {domain}')


@cli_whitelist.command('add')
@click.argument('instance')
def cli_whitelist_add(instance: str) -> None:
	'Add an instance to the whitelist'

	if not app.config.add_whitelist(instance):
		click.echo(f'Instance already in the whitelist: {instance}')
		return

	app.config.save()
	click.echo(f'Instance added to the whitelist: {instance}')


@cli_whitelist.command('remove')
@click.argument('instance')
def cli_whitelist_remove(instance: str) -> None:
	'Remove an instance from the whitelist'

	if not app.config.del_whitelist(instance):
		click.echo(f'Instance not in the whitelist: {instance}')
		return

	app.config.save()

	if app.config.whitelist_enabled:
		if app.database.del_inbox(instance):
			app.database.save()

	click.echo(f'Removed instance from the whitelist: {instance}')


@cli_whitelist.command('import')
def cli_whitelist_import() -> None:
	'Add all current inboxes to the whitelist'

	for domain in app.database.hostnames:
		cli_whitelist_add.callback(domain)


def main() -> None:
	# pylint: disable=no-value-for-parameter
	cli(prog_name='relay')


if __name__ == '__main__':
	click.echo('Running relay.manage is depreciated. Run `activityrelay [command]` instead.')
