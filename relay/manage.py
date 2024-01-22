from __future__ import annotations

import Crypto
import asyncio
import click
import platform
import typing

from aputils.signer import Signer
from pathlib import Path
from shutil import copyfile
from urllib.parse import urlparse

from . import __version__
from . import http_client as http
from . import logger as logging
from .application import Application
from .compat import RelayConfig, RelayDatabase
from .database import get_database
from .database.connection import RELAY_SOFTWARE
from .misc import IS_DOCKER, Message, check_open_port

if typing.TYPE_CHECKING:
	from tinysql import Row
	from typing import Any, Optional


# pylint: disable=unsubscriptable-object,unsupported-assignment-operation


CONFIG_IGNORE = (
	'schema-version',
	'private-key'
)

ACTOR_FORMATS = {
	'mastodon': 'https://{domain}/actor',
	'akkoma': 'https://{domain}/relay',
	'pleroma': 'https://{domain}/relay'
}

SOFTWARE = (
	'mastodon',
	'akkoma',
	'pleroma',
	'misskey',
	'friendica',
	'hubzilla',
	'firefish',
	'gotosocial'
)


@click.group('cli', context_settings={'show_default': True}, invoke_without_command=True)
@click.option('--config', '-c', default='relay.yaml', help='path to the relay\'s config')
@click.version_option(version=__version__, prog_name='ActivityRelay')
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
	ctx.obj = Application(config)

	if not ctx.invoked_subcommand:
		if ctx.obj.config.domain.endswith('example.com'):
			cli_setup.callback()

		else:
			cli_run.callback()


@cli.command('setup')
@click.pass_context
def cli_setup(ctx: click.Context) -> None:
	'Generate a new config'

	while True:
		ctx.obj.config.domain = click.prompt(
			'What domain will the relay be hosted on?',
			default = ctx.obj.config.domain
		)

		if not ctx.obj.config.domain.endswith('example.com'):
			break

		click.echo('The domain must not end with "example.com"')

	if not IS_DOCKER:
		ctx.obj.config.listen = click.prompt(
			'Which address should the relay listen on?',
			default = ctx.obj.config.listen
		)

		ctx.obj.config.port = click.prompt(
			'What TCP port should the relay listen on?',
			default = ctx.obj.config.port,
			type = int
		)

	ctx.obj.config.db_type = click.prompt(
		'Which database backend will be used?',
		default = ctx.obj.config.db_type,
		type = click.Choice(['postgres', 'sqlite'], case_sensitive = False)
	)

	if ctx.obj.config.db_type == 'sqlite':
		ctx.obj.config.sq_path = click.prompt(
			'Where should the database be stored?',
			default = ctx.obj.config.sq_path
		)

	elif ctx.obj.config.db_type == 'postgres':
		ctx.obj.config.pg_name = click.prompt(
			'What is the name of the database?',
			default = ctx.obj.config.pg_name
		)

		ctx.obj.config.pg_host = click.prompt(
			'What IP address or hostname does the server listen on?',
			default = ctx.obj.config.pg_host
		)

		ctx.obj.config.pg_port = click.prompt(
			'What port does the server listen on?',
			default = ctx.obj.config.pg_port,
			type = int
		)

		ctx.obj.config.pg_user = click.prompt(
			'Which user will authenticate with the server?',
			default = ctx.obj.config.pg_user
		)

		ctx.obj.config.pg_pass = click.prompt(
			'User password: ',
			hide_input = True
		) or None

	ctx.obj.config.save()

	config = {
		'private-key': Signer.new('n/a').export()
	}

	with ctx.obj.database.connection() as conn:
		for key, value in config.items():
			conn.put_config(key, value)

	if not IS_DOCKER and click.confirm('Relay all setup! Would you like to run it now?'):
		cli_run.callback()


@cli.command('run')
@click.pass_context
def cli_run(ctx: click.Context) -> None:
	'Run the relay'

	if ctx.obj.config.domain.endswith('example.com') or not ctx.obj.signer:
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

	if not check_open_port(ctx.obj.config.listen, ctx.obj.config.port):
		click.echo(f'Error: A server is already running on port {ctx.obj.config.port}')
		return

	ctx.obj.run()


@cli.command('convert')
@click.option('--old-config', '-o', help = 'Path to the new config file')
@click.pass_context
def cli_convert(ctx: click.Context, old_config: str) -> None:
	'Convert an old config and jsonld database to the new format.'

	old_config = Path(old_config).expanduser().resolve()
	backup = ctx.obj.config.path.parent.joinpath(f'{ctx.obj.config.path.stem}.backup.yaml')

	if str(old_config) == str(ctx.obj.config.path) and not backup.exists():
		logging.info('Created backup config @ %s', backup)
		copyfile(ctx.obj.config.path, backup)

	config = RelayConfig(old_config)
	config.load()

	database = RelayDatabase(config)
	database.load()

	ctx.obj.config.set('listen', config['listen'])
	ctx.obj.config.set('port', config['port'])
	ctx.obj.config.set('workers', config['workers'])
	ctx.obj.config.set('sq_path', config['db'].replace('jsonld', 'sqlite3'))

	with get_database(ctx.obj.config) as db:
		with db.connection() as conn:
			conn.put_config('private-key', database['private-key'])
			conn.put_config('note', config['note'])
			conn.put_config('whitelist-enabled', config['whitelist_enabled'])

			with click.progressbar(
				database['relay-list'].values(),
				label = 'Inboxes'.ljust(15),
				width = 0
			) as inboxes:

				for inbox in inboxes:
					if inbox['software'] in ('akkoma', 'pleroma'):
						actor = f'https://{inbox["domain"]}/relay'

					elif inbox['software'] == 'mastodon':
						actor = f'https://{inbox["domain"]}/actor'

					else:
						actor = None

					conn.put_inbox(
						inbox['domain'],
						inbox['inbox'],
						actor = actor,
						followid = inbox['followid'],
						software = inbox['software']
					)

			with click.progressbar(
				config['blocked_software'],
				label = 'Banned software'.ljust(15),
				width = 0
			) as banned_software:

				for software in banned_software:
					conn.put_software_ban(
						software,
						reason = 'relay' if software in RELAY_SOFTWARE else None
					)

			with click.progressbar(
				config['blocked_instances'],
				label = 'Banned domains'.ljust(15),
				width = 0
			) as banned_software:

				for domain in banned_software:
					conn.put_domain_ban(domain)

			with click.progressbar(
				config['whitelist'],
				label = 'Whitelist'.ljust(15),
				width = 0
			) as whitelist:

				for instance in whitelist:
					conn.put_domain_whitelist(instance)

	click.echo('Finished converting old config and database :3')


@cli.command('edit-config')
@click.option('--editor', '-e', help = 'Text editor to use')
@click.pass_context
def cli_editconfig(ctx: click.Context, editor: str) -> None:
	'Edit the config file'

	click.edit(
		editor = editor,
		filename = str(ctx.obj.config.path)
	)


@cli.group('config')
def cli_config() -> None:
	'Manage the relay settings stored in the database'


@cli_config.command('list')
@click.pass_context
def cli_config_list(ctx: click.Context) -> None:
	'List the current relay config'

	click.echo('Relay Config:')

	with ctx.obj.database.connection() as conn:
		for key, value in conn.get_config_all().items():
			if key not in CONFIG_IGNORE:
				key = f'{key}:'.ljust(20)
				click.echo(f'- {key} {value}')


@cli_config.command('set')
@click.argument('key')
@click.argument('value')
@click.pass_context
def cli_config_set(ctx: click.Context, key: str, value: Any) -> None:
	'Set a config value'

	with ctx.obj.database.connection() as conn:
		new_value = conn.put_config(key, value)

	print(f'{key}: {repr(new_value)}')


@cli.group('inbox')
def cli_inbox() -> None:
	'Manage the inboxes in the database'


@cli_inbox.command('list')
@click.pass_context
def cli_inbox_list(ctx: click.Context) -> None:
	'List the connected instances or relays'

	click.echo('Connected to the following instances or relays:')

	with ctx.obj.database.connection() as conn:
		for inbox in conn.execute('SELECT * FROM inboxes'):
			click.echo(f'- {inbox["inbox"]}')


@cli_inbox.command('follow')
@click.argument('actor')
@click.pass_context
def cli_inbox_follow(ctx: click.Context, actor: str) -> None:
	'Follow an actor (Relay must be running)'

	with ctx.obj.database.connection() as conn:
		if conn.get_domain_ban(actor):
			click.echo(f'Error: Refusing to follow banned actor: {actor}')
			return

		if (inbox_data := conn.get_inbox(actor)):
			inbox = inbox_data['inbox']

		else:
			if not actor.startswith('http'):
				actor = f'https://{actor}/actor'

			actor_data = asyncio.run(http.get(actor, sign_headers = True))

			if not actor_data:
				click.echo(f'Failed to fetch actor: {actor}')
				return

			inbox = actor_data.shared_inbox

	message = Message.new_follow(
		host = ctx.obj.config.domain,
		actor = actor
	)

	asyncio.run(http.post(inbox, message))
	click.echo(f'Sent follow message to actor: {actor}')


@cli_inbox.command('unfollow')
@click.argument('actor')
@click.pass_context
def cli_inbox_unfollow(ctx: click.Context, actor: str) -> None:
	'Unfollow an actor (Relay must be running)'

	inbox_data: Row = None

	with ctx.obj.database.connection() as conn:
		if conn.get_domain_ban(actor):
			click.echo(f'Error: Refusing to follow banned actor: {actor}')
			return

		if (inbox_data := conn.get_inbox(actor)):
			inbox = inbox_data['inbox']
			message = Message.new_unfollow(
				host = ctx.obj.config.domain,
				actor = actor,
				follow = inbox_data['followid']
			)

		else:
			if not actor.startswith('http'):
				actor = f'https://{actor}/actor'

			actor_data = asyncio.run(http.get(actor, sign_headers = True))
			inbox = actor_data.shared_inbox
			message = Message.new_unfollow(
				host = ctx.obj.config.domain,
				actor = actor,
				follow = {
					'type': 'Follow',
					'object': actor,
					'actor': f'https://{ctx.obj.config.domain}/actor'
				}
			)

	asyncio.run(http.post(inbox, message))
	click.echo(f'Sent unfollow message to: {actor}')


@cli_inbox.command('add')
@click.argument('inbox')
@click.option('--actor', '-a', help = 'Actor url for the inbox')
@click.option('--followid', '-f', help = 'Url for the follow activity')
@click.option('--software', '-s', type = click.Choice(SOFTWARE))
@click.pass_context
def cli_inbox_add(
				ctx: click.Context,
				inbox: str,
				actor: Optional[str] = None,
				followid: Optional[str] = None,
				software: Optional[str] = None) -> None:
	'Add an inbox to the database'

	if not inbox.startswith('http'):
		domain = inbox
		inbox = f'https://{inbox}/inbox'

	else:
		domain = urlparse(inbox).netloc

	if not actor and software:
		try:
			actor = ACTOR_FORMATS[software].format(domain = domain)

		except KeyError:
			pass

	with ctx.obj.database.connection() as conn:
		if conn.get_domain_ban(domain):
			click.echo(f'Refusing to add banned inbox: {inbox}')
			return

		if conn.get_inbox(inbox):
			click.echo(f'Error: Inbox already in database: {inbox}')
			return

		conn.put_inbox(domain, inbox, actor, followid, software)

	click.echo(f'Added inbox to the database: {inbox}')


@cli_inbox.command('remove')
@click.argument('inbox')
@click.pass_context
def cli_inbox_remove(ctx: click.Context, inbox: str) -> None:
	'Remove an inbox from the database'

	with ctx.obj.database.connection() as conn:
		if not conn.del_inbox(inbox):
			click.echo(f'Inbox not in database: {inbox}')
			return

	click.echo(f'Removed inbox from the database: {inbox}')


@cli.group('instance')
def cli_instance() -> None:
	'Manage instance bans'


@cli_instance.command('list')
@click.pass_context
def cli_instance_list(ctx: click.Context) -> None:
	'List all banned instances'

	click.echo('Banned domains:')

	with ctx.obj.database.connection() as conn:
		for instance in conn.execute('SELECT * FROM domain_bans'):
			if instance['reason']:
				click.echo(f'- {instance["domain"]} ({instance["reason"]})')

			else:
				click.echo(f'- {instance["domain"]}')


@cli_instance.command('ban')
@click.argument('domain')
@click.option('--reason', '-r', help = 'Public note about why the domain is banned')
@click.option('--note', '-n', help = 'Internal note that will only be seen by admins and mods')
@click.pass_context
def cli_instance_ban(ctx: click.Context, domain: str, reason: str, note: str) -> None:
	'Ban an instance and remove the associated inbox if it exists'

	with ctx.obj.database.connection() as conn:
		if conn.get_domain_ban(domain):
			click.echo(f'Domain already banned: {domain}')
			return

		conn.put_domain_ban(domain, reason, note)
		conn.del_inbox(domain)
		click.echo(f'Banned instance: {domain}')


@cli_instance.command('unban')
@click.argument('domain')
@click.pass_context
def cli_instance_unban(ctx: click.Context, domain: str) -> None:
	'Unban an instance'

	with ctx.obj.database.connection() as conn:
		if not conn.del_domain_ban(domain):
			click.echo(f'Instance wasn\'t banned: {domain}')
			return

		click.echo(f'Unbanned instance: {domain}')


@cli_instance.command('update')
@click.argument('domain')
@click.option('--reason', '-r')
@click.option('--note', '-n')
@click.pass_context
def cli_instance_update(ctx: click.Context, domain: str, reason: str, note: str) -> None:
	'Update the public reason or internal note for a domain ban'

	if not (reason or note):
		ctx.fail('Must pass --reason or --note')

	with ctx.obj.database.connection() as conn:
		if not (row := conn.update_domain_ban(domain, reason, note)):
			click.echo(f'Failed to update domain ban: {domain}')
			return

		click.echo(f'Updated domain ban: {domain}')

		if row['reason']:
			click.echo(f'- {row["domain"]} ({row["reason"]})')

		else:
			click.echo(f'- {row["domain"]}')


@cli.group('software')
def cli_software() -> None:
	'Manage banned software'


@cli_software.command('list')
@click.pass_context
def cli_software_list(ctx: click.Context) -> None:
	'List all banned software'

	click.echo('Banned software:')

	with ctx.obj.database.connection() as conn:
		for software in conn.execute('SELECT * FROM software_bans'):
			if software['reason']:
				click.echo(f'- {software["name"]} ({software["reason"]})')

			else:
				click.echo(f'- {software["name"]}')


@cli_software.command('ban')
@click.argument('name')
@click.option('--reason', '-r')
@click.option('--note', '-n')
@click.option(
	'--fetch-nodeinfo', '-f',
	is_flag = True,
	help = 'Treat NAME like a domain and try to fetch the software name from nodeinfo'
)
@click.pass_context
def cli_software_ban(ctx: click.Context,
					name: str,
					reason: str,
					note: str,
					fetch_nodeinfo: bool) -> None:
	'Ban software. Use RELAYS for NAME to ban relays'

	with ctx.obj.database.connection() as conn:
		if name == 'RELAYS':
			for software in RELAY_SOFTWARE:
				if conn.get_software_ban(software):
					click.echo(f'Relay already banned: {software}')
					continue

				conn.put_software_ban(software, reason or 'relay', note)

			click.echo('Banned all relay software')
			return

		if fetch_nodeinfo:
			nodeinfo = asyncio.run(http.fetch_nodeinfo(name))

			if not nodeinfo:
				click.echo(f'Failed to fetch software name from domain: {name}')
				return

			name = nodeinfo.sw_name

		if conn.get_software_ban(name):
			click.echo(f'Software already banned: {name}')
			return

		if not conn.put_software_ban(name, reason, note):
			click.echo(f'Failed to ban software: {name}')
			return

		click.echo(f'Banned software: {name}')


@cli_software.command('unban')
@click.argument('name')
@click.option('--reason', '-r')
@click.option('--note', '-n')
@click.option(
	'--fetch-nodeinfo', '-f',
	is_flag = True,
	help = 'Treat NAME like a domain and try to fetch the software name from nodeinfo'
)
@click.pass_context
def cli_software_unban(ctx: click.Context, name: str, fetch_nodeinfo: bool) -> None:
	'Ban software. Use RELAYS for NAME to unban relays'

	with ctx.obj.database.connection() as conn:
		if name == 'RELAYS':
			for software in RELAY_SOFTWARE:
				if not conn.del_software_ban(software):
					click.echo(f'Relay was not banned: {software}')

			click.echo('Unbanned all relay software')
			return

		if fetch_nodeinfo:
			nodeinfo = asyncio.run(http.fetch_nodeinfo(name))

			if not nodeinfo:
				click.echo(f'Failed to fetch software name from domain: {name}')
				return

			name = nodeinfo.sw_name

		if not conn.del_software_ban(name):
			click.echo(f'Software was not banned: {name}')
			return

		click.echo(f'Unbanned software: {name}')


@cli_software.command('update')
@click.argument('name')
@click.option('--reason', '-r')
@click.option('--note', '-n')
@click.pass_context
def cli_software_update(ctx: click.Context, name: str, reason: str, note: str) -> None:
	'Update the public reason or internal note for a software ban'

	if not (reason or note):
		ctx.fail('Must pass --reason or --note')

	with ctx.obj.database.connection() as conn:
		if not (row := conn.update_software_ban(name, reason, note)):
			click.echo(f'Failed to update software ban: {name}')
			return

		click.echo(f'Updated software ban: {name}')

		if row['reason']:
			click.echo(f'- {row["name"]} ({row["reason"]})')

		else:
			click.echo(f'- {row["name"]}')


@cli.group('whitelist')
def cli_whitelist() -> None:
	'Manage the instance whitelist'


@cli_whitelist.command('list')
@click.pass_context
def cli_whitelist_list(ctx: click.Context) -> None:
	'List all the instances in the whitelist'

	click.echo('Current whitelisted domains:')

	with ctx.obj.database.connection() as conn:
		for domain in conn.execute('SELECT * FROM whitelist'):
			click.echo(f'- {domain["domain"]}')


@cli_whitelist.command('add')
@click.argument('domain')
@click.pass_context
def cli_whitelist_add(ctx: click.Context, domain: str) -> None:
	'Add a domain to the whitelist'

	with ctx.obj.database.connection() as conn:
		if conn.get_domain_whitelist(domain):
			click.echo(f'Instance already in the whitelist: {domain}')
			return

		conn.put_domain_whitelist(domain)
		click.echo(f'Instance added to the whitelist: {domain}')


@cli_whitelist.command('remove')
@click.argument('domain')
@click.pass_context
def cli_whitelist_remove(ctx: click.Context, domain: str) -> None:
	'Remove an instance from the whitelist'

	with ctx.obj.database.connection() as conn:
		if not conn.del_domain_whitelist(domain):
			click.echo(f'Domain not in the whitelist: {domain}')
			return

		if conn.get_config('whitelist-enabled'):
			if conn.del_inbox(domain):
				click.echo(f'Removed inbox for domain: {domain}')

		click.echo(f'Removed domain from the whitelist: {domain}')


@cli_whitelist.command('import')
@click.pass_context
def cli_whitelist_import(ctx: click.Context) -> None:
	'Add all current inboxes to the whitelist'

	with ctx.obj.database.connection() as conn:
		for inbox in conn.execute('SELECT * FROM inboxes').all():
			if conn.get_domain_whitelist(inbox['domain']):
				click.echo(f'Domain already in whitelist: {inbox["domain"]}')
				continue

			conn.put_domain_whitelist(inbox['domain'])

		click.echo('Imported whitelist from inboxes')


def main() -> None:
	# pylint: disable=no-value-for-parameter
	cli(prog_name='relay')


if __name__ == '__main__':
	click.echo('Running relay.manage is depreciated. Run `activityrelay [command]` instead.')
