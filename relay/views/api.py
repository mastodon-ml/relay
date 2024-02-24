from __future__ import annotations

import typing

from aiohttp import web
from argon2.exceptions import VerifyMismatchError
from urllib.parse import urlparse

from .base import View, register_route

from .. import __version__
from .. import logger as logging
from ..database.config import CONFIG_DEFAULTS
from ..misc import Message, Response

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from collections.abc import Coroutine


CONFIG_IGNORE = (
	'schema-version',
	'private-key'
)

CONFIG_VALID = {key for key in CONFIG_DEFAULTS if key not in CONFIG_IGNORE}

PUBLIC_API_PATHS: tuple[tuple[str, str]] = (
	('GET', '/api/v1/relay'),
	('GET', '/api/v1/instance'),
	('POST', '/api/v1/token')
)


def check_api_path(method: str, path: str) -> bool:
	if path.startswith('/api/doc') or (method, path) in PUBLIC_API_PATHS:
		return False

	return path.startswith('/api')


@web.middleware
async def handle_api_path(request: web.Request, handler: Coroutine) -> web.Response:
	try:
		request['token'] = request.headers['Authorization'].replace('Bearer', '').strip()

		with request.app.database.session() as conn:
			request['user'] = conn.get_user_by_token(request['token'])

	except (KeyError, ValueError):
		request['token'] = None
		request['user'] = None

	if check_api_path(request.method, request.path):
		if not request['token']:
			return Response.new_error(401, 'Missing token', 'json')

		if not request['user']:
			return Response.new_error(401, 'Invalid token', 'json')

	return await handler(request)


# pylint: disable=no-self-use,unused-argument

@register_route('/api/v1/token')
class Login(View):
	async def get(self, request: Request) -> Response:
		return Response.new({'message': 'Token valid'}, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['username', 'password'], [])

		if isinstance(data, Response):
			return data

		with self.database.connction(True) as conn:
			if not (user := conn.get_user(data['username'])):
				return Response.new_error(401, 'User not found', 'json')

			try:
				conn.hasher.verify(user['hash'], data['password'])

			except VerifyMismatchError:
				return Response.new_error(401, 'Invalid password', 'json')

			token = conn.put_token(data['username'])

		return Response.new({'token': token['code']}, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		with self.database.session() as conn:
			conn.del_token(request['token'])

		return Response.new({'message': 'Token revoked'}, ctype = 'json')


@register_route('/api/v1/relay')
class RelayInfo(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			config = conn.get_config_all()
			inboxes = [row['domain'] for row in conn.execute('SELECT * FROM inboxes')]

		data = {
			'domain': self.config.domain,
			'name': config['name'],
			'description': config['note'],
			'version': __version__,
			'whitelist_enabled': config['whitelist-enabled'],
			'email': None,
			'admin': None,
			'icon': None,
			'instances': inboxes
		}

		return Response.new(data, ctype = 'json')


@register_route('/api/v1/config')
class Config(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = conn.get_config_all()
			data['log-level'] = data['log-level'].name

		for key in CONFIG_IGNORE:
			del data[key]

		return Response.new(data, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['key', 'value'], [])

		if isinstance(data, Response):
			return data

		if data['key'] not in CONFIG_VALID:
			return Response.new_error(400, 'Invalid key', 'json')

		with self.database.session() as conn:
			conn.put_config(data['key'], data['value'])

		return Response.new({'message': 'Updated config'}, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['key'], [])

		if isinstance(data, Response):
			return data

		if data['key'] not in CONFIG_VALID:
			return Response.new_error(400, 'Invalid key', 'json')

		with self.database.session() as conn:
			conn.put_config(data['key'], CONFIG_DEFAULTS[data['key']][1])

		return Response.new({'message': 'Updated config'}, ctype = 'json')


@register_route('/api/v1/instance')
class Inbox(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = tuple(conn.execute('SELECT * FROM inboxes').all())

		return Response.new(data, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['actor'], ['inbox', 'software', 'followid'])

		if isinstance(data, Response):
			return data

		data['domain'] = urlparse(data["actor"]).netloc

		with self.database.session() as conn:
			if conn.get_inbox(data['domain']):
				return Response.new_error(404, 'Instance already in database', 'json')

			if not data.get('inbox'):
				try:
					actor_data = await self.client.get(
						data['actor'],
						sign_headers = True,
						loads = Message.parse
					)

					data['inbox'] = actor_data.shared_inbox

				except Exception as e:
					logging.error('Failed to fetch actor: %s', str(e))
					return Response.new_error(500, 'Failed to fetch actor', 'json')

			row = conn.put_inbox(**data)

		return Response.new(row, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], ['actor', 'software', 'followid'])

			if isinstance(data, Response):
				return data

			if not (instance := conn.get_inbox(data['domain'])):
				return Response.new_error(404, 'Instance with domain not found', 'json')

			instance = conn.update_inbox(instance['inbox'], **data)

		return Response.new(instance, ctype = 'json')


	async def delete(self, request: Request, domain: str) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], [])

			if isinstance(data, Response):
				return data

			if not conn.get_inbox(data['domain']):
				return Response.new_error(404, 'Instance with domain not found', 'json')

			conn.del_inbox(data['domain'])

		return Response.new({'message': 'Deleted instance'}, ctype = 'json')


@register_route('/api/v1/domain_ban')
class DomainBan(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			bans = tuple(conn.execute('SELECT * FROM domain_bans').all())

		return Response.new(bans, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['domain'], ['note', 'reason'])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if conn.get_domain_ban(data['domain']):
				return Response.new_error(400, 'Domain already banned', 'json')

			ban = conn.put_domain_ban(**data)

		return Response.new(ban, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], ['note', 'reason'])

			if isinstance(data, Response):
				return data

			if not conn.get_domain_ban(data['domain']):
				return Response.new_error(404, 'Domain not banned', 'json')

			if not any([data.get('note'), data.get('reason')]):
				return Response.new_error(400, 'Must include note and/or reason parameters', 'json')

			ban = conn.update_domain_ban(data['domain'], **data)

		return Response.new(ban, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], [])

			if isinstance(data, Response):
				return data

			if not conn.get_domain_ban(data['domain']):
				return Response.new_error(404, 'Domain not banned', 'json')

			conn.del_domain_ban(data['domain'])

		return Response.new({'message': 'Unbanned domain'}, ctype = 'json')


@register_route('/api/v1/software_ban')
class SoftwareBan(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			bans = tuple(conn.execute('SELECT * FROM software_bans').all())

		return Response.new(bans, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['name'], ['note', 'reason'])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if conn.get_software_ban(data['name']):
				return Response.new_error(400, 'Domain already banned', 'json')

			ban = conn.put_software_ban(**data)

		return Response.new(ban, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		data = await self.get_api_data(['name'], ['note', 'reason'])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if not conn.get_software_ban(data['name']):
				return Response.new_error(404, 'Software not banned', 'json')

			if not any([data.get('note'), data.get('reason')]):
				return Response.new_error(400, 'Must include note and/or reason parameters', 'json')

			ban = conn.update_software_ban(data['name'], **data)

		return Response.new(ban, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['name'], [])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if not conn.get_software_ban(data['name']):
				return Response.new_error(404, 'Software not banned', 'json')

			conn.del_software_ban(data['name'])

		return Response.new({'message': 'Unbanned software'}, ctype = 'json')


@register_route('/api/v1/whitelist')
class Whitelist(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			items = tuple(conn.execute('SELECT * FROM whitelist').all())

		return Response.new(items, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['domain'], [])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if conn.get_domain_whitelist(data['domain']):
				return Response.new_error(400, 'Domain already added to whitelist', 'json')

			item = conn.put_domain_whitelist(**data)

		return Response.new(item, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['domain'], [])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if not conn.get_domain_whitelist(data['domain']):
				return Response.new_error(404, 'Domain not in whitelist', 'json')

			conn.del_domain_whitelist(data['domain'])

		return Response.new({'message': 'Removed domain from whitelist'}, ctype = 'json')
