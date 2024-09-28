from __future__ import annotations

import aputils
import asyncio
import click
import json
import os

from pathlib import Path
from shutil import copyfile
from typing import Any
from urllib.parse import urlparse

from . import __version__
from . import http_client as http
from . import logger as logging
from .application import Application
from .compat import RelayConfig, RelayDatabase
from .config import Config
from .database import RELAY_SOFTWARE, get_database, schema
from .misc import ACTOR_FORMATS, SOFTWARE, IS_DOCKER, Message


def check_alphanumeric(text: str) -> str:
	if not text.isalnum():
		raise click.BadParameter('String not alphanumeric')

	return text


@click.group('cli', context_settings = {'show_default': True})
@click.option('--config', '-c', type = Path, help = 'path to the relay\'s config')
@click.version_option(version = __version__, prog_name = 'ActivityRelay')
@click.pass_context
def cli(ctx: click.Context, config: Path | None) -> None:
	if IS_DOCKER:
		config = Path("/data/relay.yaml")

		# The database was named "relay.jsonld" even though it's an sqlite file. Fix it.
		db = Path('/data/relay.sqlite3')
		wrongdb = Path('/data/relay.jsonld')

		if wrongdb.exists() and not db.exists():
			try:
				with wrongdb.open('rb') as fd:
					json.load(fd)

			except json.JSONDecodeError:
				wrongdb.rename(db)

	ctx.obj = Application(config)


@cli.command('setup')
@click.option('--skip-questions', '-s', is_flag = True, help = 'Just setup the database')
@click.pass_context
def cli_setup(ctx: click.Context, skip_questions: bool) -> None:
	'Generate a new config and create the database'

	if ctx.obj.signer is not None:
		if not click.prompt('The database is already setup. Are you sure you want to continue?'):
			return

	if skip_questions and ctx.obj.config.domain.endswith('example.com'):
		click.echo('You cannot skip the questions if the relay is not configured yet')
		return

	if not skip_questions:
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

		if ctx.obj.config.db_type == 'sqlite' and not IS_DOCKER:
			ctx.obj.config.sq_path = click.prompt(
				'Where should the database be stored?',
				default = ctx.obj.config.sq_path
			)

		elif ctx.obj.config.db_type == 'postgres':
			config_postgresql(ctx.obj.config)

		ctx.obj.config.ca_type = click.prompt(
			'Which caching backend?',
			default = ctx.obj.config.ca_type,
			type = click.Choice(['database', 'redis'], case_sensitive = False)
		)

		if ctx.obj.config.ca_type == 'redis':
			ctx.obj.config.rd_host = click.prompt(
				'What IP address, hostname, or unix socket does the server listen on?',
				default = ctx.obj.config.rd_host
			)

			ctx.obj.config.rd_port = click.prompt(
				'What port does the server listen on?',
				default = ctx.obj.config.rd_port,
				type = int
			)

			ctx.obj.config.rd_user = click.prompt(
				'Which user will authenticate with the server',
				default = ctx.obj.config.rd_user
			)

			ctx.obj.config.rd_pass = click.prompt(
				'User password',
				hide_input = True,
				show_default = False,
				default = ctx.obj.config.rd_pass or ""
			) or None

			ctx.obj.config.rd_database = click.prompt(
				'Which database number to use?',
				default = ctx.obj.config.rd_database,
				type = int
			)

			ctx.obj.config.rd_prefix = click.prompt(
				'What text should each cache key be prefixed with?',
				default = ctx.obj.config.rd_database,
				type = check_alphanumeric
			)

		ctx.obj.config.save()

	config = {
		'private-key': aputils.Signer.new('n/a').export()
	}

	with ctx.obj.database.session() as conn:
		for key, value in config.items():
			conn.put_config(key, value)

	if IS_DOCKER:
		click.echo("Relay all setup! Start the container to run the relay.")
		return

	if click.confirm('Relay all setup! Would you like to run it now?'):
		cli_run.callback() # type: ignore


@cli.command('run')
@click.option('--dev', '-d', is_flag=True, help='Enable developer mode')
@click.pass_context
def cli_run(ctx: click.Context, dev: bool = False) -> None:
	'Run the relay'

	if ctx.obj.config.domain.endswith('example.com') or ctx.obj.signer is None:
		if not IS_DOCKER:
			click.echo('Relay is not set up. Please run "activityrelay setup".')

			return

		cli_setup.callback() # type: ignore
		return

	ctx.obj['dev'] = dev
	ctx.obj.run()

	# todo: figure out why the relay doesn't quit properly without this
	os._exit(0)


@cli.command('db-maintenance')
@click.pass_context
def cli_db_maintenance(ctx: click.Context) -> None:
	'Perform maintenance tasks on the database'

	if ctx.obj.config.db_type == "postgres":
		return

	with ctx.obj.database.session(False) as s:
		with s.transaction():
			s.fix_timestamps()

		with s.execute("VACUUM"):
			pass


@cli.command('convert')
@click.option('--old-config', '-o', help = 'Path to the config file to convert from')
@click.pass_context
def cli_convert(ctx: click.Context, old_config: str) -> None:
	'Convert an old config and jsonld database to the new format.'

	old_config = Path(old_config).expanduser().resolve() if old_config else ctx.obj.config.path
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
	ctx.obj.config.set('domain', config['host'])
	ctx.obj.config.save()

	# fix: mypy complains about the types returned by click.progressbar when updating click to 8.1.7
	with get_database(ctx.obj.config) as db:
		with db.session(True) as conn:
			conn.put_config('private-key', database['private-key'])
			conn.put_config('note', config['note'])
			conn.put_config('whitelist-enabled', config['whitelist_enabled'])

			with click.progressbar(
				database['relay-list'].values(),
				label = 'Inboxes'.ljust(15),
				width = 0
			) as inboxes:
				for inbox in inboxes:
					if inbox['software'] in {'akkoma', 'pleroma'}:
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


@cli.command('switch-backend')
@click.pass_context
def cli_switchbackend(ctx: click.Context) -> None:
	"""
		Copy the database from one backend to the other

		Be sure to set the database type to the backend you want to convert from. For instance, set
		the database type to `sqlite`, fill out the connection details for postgresql, and the
		data from the sqlite database will be copied to the postgresql database. This only works if
		the database in postgresql already exists.
	"""

	config = Config(ctx.obj.config.path, load = True)
	config.db_type = "sqlite" if config.db_type == "postgres" else "postgres"

	if config.db_type == "postgres":
		if click.confirm("Setup PostgreSQL configuration?"):
			config_postgresql(config)

		order = ("SQLite", "PostgreSQL")
		click.pause("Make sure the database and user already exist before continuing")

	else:
		order = ("PostgreSQL", "SQLite")

	click.echo(f"About to convert from {order[0]} to {order[1]}...")
	database = get_database(config, migrate = False)

	with database.session(True) as new, ctx.obj.database.session(False) as old:
		if click.confirm("All tables in the destination database will be dropped. Continue?"):
			new.drop_tables()

		new.create_tables()

		for table in schema.TABLES.keys():
			for row in old.execute(f"SELECT * FROM {table}"):
				new.insert(table, row).close()

		config.save()
		click.echo("Done!")


@cli.group('config')
def cli_config() -> None:
	'Manage the relay settings stored in the database'


@cli_config.command('list')
@click.pass_context
def cli_config_list(ctx: click.Context) -> None:
	'List the current relay config'

	click.echo('Relay Config:')

	with ctx.obj.database.session() as conn:
		config = conn.get_config_all()

		for key, value in config.to_dict().items():
			if key in type(config).SYSTEM_KEYS():
				continue

			if key == 'log-level':
				value = value.name

			key_str = f'{key}:'.ljust(20)
			click.echo(f'- {key_str} {repr(value)}')


@cli_config.command('set')
@click.argument('key')
@click.argument('value')
@click.pass_context
def cli_config_set(ctx: click.Context, key: str, value: Any) -> None:
	'Set a config value'

	try:
		with ctx.obj.database.session() as conn:
			new_value = conn.put_config(key, value)

	except Exception:
		click.echo(f'Invalid config name: {key}')
		return

	click.echo(f'{key}: {repr(new_value)}')


@cli.group('user')
def cli_user() -> None:
	'Manage local users'


@cli_user.command('list')
@click.pass_context
def cli_user_list(ctx: click.Context) -> None:
	'List all local users'

	click.echo('Users:')

	with ctx.obj.database.session() as conn:
		for row in conn.get_users():
			click.echo(f'- {row.username}')


@cli_user.command('create')
@click.argument('username')
@click.argument('handle', required = False)
@click.pass_context
def cli_user_create(ctx: click.Context, username: str, handle: str) -> None:
	'Create a new local user'

	with ctx.obj.database.session() as conn:
		if conn.get_user(username) is not None:
			click.echo(f'User already exists: {username}')
			return

		while True:
			if not (password := click.prompt('New password', hide_input = True)):
				click.echo('No password provided')
				continue

			if password != click.prompt('New password again', hide_input = True):
				click.echo('Passwords do not match')
				continue

			break

		conn.put_user(username, password, handle)

	click.echo(f'Created user "{username}"')


@cli_user.command('delete')
@click.argument('username')
@click.pass_context
def cli_user_delete(ctx: click.Context, username: str) -> None:
	'Delete a local user'

	with ctx.obj.database.session() as conn:
		if conn.get_user(username) is None:
			click.echo(f'User does not exist: {username}')
			return

		conn.del_user(username)

	click.echo(f'Deleted user "{username}"')


@cli_user.command('list-tokens')
@click.argument('username')
@click.pass_context
def cli_user_list_tokens(ctx: click.Context, username: str) -> None:
	'List all API tokens for a user'

	click.echo(f'Tokens for "{username}":')

	with ctx.obj.database.session() as conn:
		for row in conn.get_tokens(username):
			click.echo(f'- {row.code}')


@cli_user.command('create-token')
@click.argument('username')
@click.pass_context
def cli_user_create_token(ctx: click.Context, username: str) -> None:
	'Create a new API token for a user'

	with ctx.obj.database.session() as conn:
		if (user := conn.get_user(username)) is None:
			click.echo(f'User does not exist: {username}')
			return

		token = conn.put_token(user.username)

	click.echo(f'New token for "{username}": {token.code}')


@cli_user.command('delete-token')
@click.argument('code')
@click.pass_context
def cli_user_delete_token(ctx: click.Context, code: str) -> None:
	'Delete an API token'

	with ctx.obj.database.session() as conn:
		if conn.get_token(code) is None:
			click.echo('Token does not exist')
			return

		conn.del_token(code)

	click.echo('Deleted token')


@cli.group('inbox')
def cli_inbox() -> None:
	'Manage the inboxes in the database'


@cli_inbox.command('list')
@click.pass_context
def cli_inbox_list(ctx: click.Context) -> None:
	'List the connected instances or relays'

	click.echo('Connected to the following instances or relays:')

	with ctx.obj.database.session() as conn:
		for row in conn.get_inboxes():
			click.echo(f'- {row.inbox}')


@cli_inbox.command('follow')
@click.argument('actor')
@click.pass_context
def cli_inbox_follow(ctx: click.Context, actor: str) -> None:
	'Follow an actor (Relay must be running)'

	instance: schema.Instance | None = None

	with ctx.obj.database.session() as conn:
		if conn.get_domain_ban(actor):
			click.echo(f'Error: Refusing to follow banned actor: {actor}')
			return

		if (instance := conn.get_inbox(actor)) is not None:
			inbox = instance.inbox

		else:
			if not actor.startswith('http'):
				actor = f'https://{actor}/actor'

			if (actor_data := asyncio.run(http.get(actor, sign_headers = True))) is None:
				click.echo(f'Failed to fetch actor: {actor}')
				return

			inbox = actor_data.shared_inbox

	message = Message.new_follow(
		host = ctx.obj.config.domain,
		actor = actor
	)

	asyncio.run(http.post(inbox, message, instance))
	click.echo(f'Sent follow message to actor: {actor}')


@cli_inbox.command('unfollow')
@click.argument('actor')
@click.pass_context
def cli_inbox_unfollow(ctx: click.Context, actor: str) -> None:
	'Unfollow an actor (Relay must be running)'

	instance: schema.Instance | None = None

	with ctx.obj.database.session() as conn:
		if conn.get_domain_ban(actor):
			click.echo(f'Error: Refusing to follow banned actor: {actor}')
			return

		if (instance := conn.get_inbox(actor)):
			inbox = instance.inbox
			message = Message.new_unfollow(
				host = ctx.obj.config.domain,
				actor = actor,
				follow = instance.followid
			)

		else:
			if not actor.startswith('http'):
				actor = f'https://{actor}/actor'

			actor_data = asyncio.run(http.get(actor, sign_headers = True))

			if not actor_data:
				click.echo("Failed to fetch actor")
				return

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

	asyncio.run(http.post(inbox, message, instance))
	click.echo(f'Sent unfollow message to: {actor}')


@cli_inbox.command('add')
@click.argument('inbox')
@click.option('--actor', '-a', help = 'Actor url for the inbox')
@click.option('--followid', '-f', help = 'Url for the follow activity')
@click.option('--software', '-s',
	type = click.Choice(SOFTWARE),
	help = 'Nodeinfo software name of the instance'
)  # noqa: E124
@click.pass_context
def cli_inbox_add(
				ctx: click.Context,
				inbox: str,
				actor: str | None = None,
				followid: str | None = None,
				software: str | None = None) -> None:
	'Add an inbox to the database'

	if not inbox.startswith('http'):
		domain = inbox
		inbox = f'https://{inbox}/inbox'

	else:
		domain = urlparse(inbox).netloc

	if not software:
		if (nodeinfo := asyncio.run(http.fetch_nodeinfo(domain))):
			software = nodeinfo.sw_name

	if not actor and software:
		try:
			actor = ACTOR_FORMATS[software].format(domain = domain)

		except KeyError:
			pass

	with ctx.obj.database.session() as conn:
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

	with ctx.obj.database.session() as conn:
		if not conn.del_inbox(inbox):
			click.echo(f'Inbox not in database: {inbox}')
			return

	click.echo(f'Removed inbox from the database: {inbox}')


@cli.group('request')
def cli_request() -> None:
	'Manage follow requests'


@cli_request.command('list')
@click.pass_context
def cli_request_list(ctx: click.Context) -> None:
	'List all current follow requests'

	click.echo('Follow requests:')

	with ctx.obj.database.session() as conn:
		for row in conn.get_requests():
			date = row.created.strftime('%Y-%m-%d')
			click.echo(f'- [{date}] {row.domain}')


@cli_request.command('accept')
@click.argument('domain')
@click.pass_context
def cli_request_accept(ctx: click.Context, domain: str) -> None:
	'Accept a follow request'

	try:
		with ctx.obj.database.session() as conn:
			instance = conn.put_request_response(domain, True)

	except KeyError:
		click.echo('Request not found')
		return

	message = Message.new_response(
		host = ctx.obj.config.domain,
		actor = instance.actor,
		followid = instance.followid,
		accept = True
	)

	asyncio.run(http.post(instance.inbox, message, instance))

	if instance.software != 'mastodon':
		message = Message.new_follow(
			host = ctx.obj.config.domain,
			actor = instance.actor
		)

		asyncio.run(http.post(instance.inbox, message, instance))


@cli_request.command('deny')
@click.argument('domain')
@click.pass_context
def cli_request_deny(ctx: click.Context, domain: str) -> None:
	'Accept a follow request'

	try:
		with ctx.obj.database.session() as conn:
			instance = conn.put_request_response(domain, False)

	except KeyError:
		click.echo('Request not found')
		return

	response = Message.new_response(
		host = ctx.obj.config.domain,
		actor = instance.actor,
		followid = instance.followid,
		accept = False
	)

	asyncio.run(http.post(instance.inbox, response, instance))


@cli.group('instance')
def cli_instance() -> None:
	'Manage instance bans'


@cli_instance.command('list')
@click.pass_context
def cli_instance_list(ctx: click.Context) -> None:
	'List all banned instances'

	click.echo('Banned domains:')

	with ctx.obj.database.session() as conn:
		for row in conn.get_domain_bans():
			if row.reason is not None:
				click.echo(f'- {row.domain} ({row.reason})')

			else:
				click.echo(f'- {row.domain}')


@cli_instance.command('ban')
@click.argument('domain')
@click.option('--reason', '-r', help = 'Public note about why the domain is banned')
@click.option('--note', '-n', help = 'Internal note that will only be seen by admins and mods')
@click.pass_context
def cli_instance_ban(ctx: click.Context, domain: str, reason: str, note: str) -> None:
	'Ban an instance and remove the associated inbox if it exists'

	with ctx.obj.database.session() as conn:
		if conn.get_domain_ban(domain) is not None:
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

	with ctx.obj.database.session() as conn:
		if conn.del_domain_ban(domain) is None:
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

	with ctx.obj.database.session() as conn:
		if not (row := conn.update_domain_ban(domain, reason, note)):
			click.echo(f'Failed to update domain ban: {domain}')
			return

		click.echo(f'Updated domain ban: {domain}')

		if row.reason:
			click.echo(f'- {row.domain} ({row.reason})')

		else:
			click.echo(f'- {row.domain}')


@cli.group('software')
def cli_software() -> None:
	'Manage banned software'


@cli_software.command('list')
@click.pass_context
def cli_software_list(ctx: click.Context) -> None:
	'List all banned software'

	click.echo('Banned software:')

	with ctx.obj.database.session() as conn:
		for row in conn.get_software_bans():
			if row.reason:
				click.echo(f'- {row.name} ({row.reason})')

			else:
				click.echo(f'- {row.name}')


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

	with ctx.obj.database.session() as conn:
		if name == 'RELAYS':
			for item in RELAY_SOFTWARE:
				if conn.get_software_ban(item):
					click.echo(f'Relay already banned: {item}')
					continue

				conn.put_software_ban(item, reason or 'relay', note)

			click.echo('Banned all relay software')
			return

		if fetch_nodeinfo:
			if not (nodeinfo := asyncio.run(http.fetch_nodeinfo(name))):
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

	with ctx.obj.database.session() as conn:
		if name == 'RELAYS':
			for software in RELAY_SOFTWARE:
				if not conn.del_software_ban(software):
					click.echo(f'Relay was not banned: {software}')

			click.echo('Unbanned all relay software')
			return

		if fetch_nodeinfo:
			if not (nodeinfo := asyncio.run(http.fetch_nodeinfo(name))):
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

	with ctx.obj.database.session() as conn:
		if not (row := conn.update_software_ban(name, reason, note)):
			click.echo(f'Failed to update software ban: {name}')
			return

		click.echo(f'Updated software ban: {name}')

		if row.reason:
			click.echo(f'- {row.name} ({row.reason})')

		else:
			click.echo(f'- {row.name}')


@cli.group('whitelist')
def cli_whitelist() -> None:
	'Manage the instance whitelist'


@cli_whitelist.command('list')
@click.pass_context
def cli_whitelist_list(ctx: click.Context) -> None:
	'List all the instances in the whitelist'

	click.echo('Current whitelisted domains:')

	with ctx.obj.database.session() as conn:
		for row in conn.get_domain_whitelist():
			click.echo(f'- {row.domain}')


@cli_whitelist.command('add')
@click.argument('domain')
@click.pass_context
def cli_whitelist_add(ctx: click.Context, domain: str) -> None:
	'Add a domain to the whitelist'

	with ctx.obj.database.session() as conn:
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

	with ctx.obj.database.session() as conn:
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
	'Add all current instances to the whitelist'

	with ctx.obj.database.session() as conn:
		for row in conn.get_inboxes():
			if conn.get_domain_whitelist(row.domain) is not None:
				click.echo(f'Domain already in whitelist: {row.domain}')
				continue

			conn.put_domain_whitelist(row.domain)

		click.echo('Imported whitelist from inboxes')


def config_postgresql(config: Config) -> None:
	config.pg_name = click.prompt(
		'What is the name of the database?',
		default = config.pg_name
	)

	config.pg_host = click.prompt(
		'What IP address, hostname, or unix socket does the server listen on?',
		default = config.pg_host,
	)

	config.pg_port = click.prompt(
		'What port does the server listen on?',
		default = config.pg_port,
		type = int
	)

	config.pg_user = click.prompt(
		'Which user will authenticate with the server?',
		default = config.pg_user
	)

	config.pg_pass = click.prompt(
		'User password',
		hide_input = True,
		show_default = False,
		default = config.pg_pass or ""
	) or None


def main() -> None:
	cli(prog_name='activityrelay')
