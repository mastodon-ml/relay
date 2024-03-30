from __future__ import annotations

import typing

from aiohttp import web
from argon2.exceptions import VerifyMismatchError
from urllib.parse import urlparse

from .base import View, register_route

from .. import __version__
from ..database import ConfigData
from ..misc import Message, Response, boolean, get_app

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from collections.abc import Callable, Sequence
	from typing import Any


ALLOWED_HEADERS = {
	'accept',
	'authorization',
	'content-type'
}

PUBLIC_API_PATHS: Sequence[tuple[str, str]] = (
	('GET', '/api/v1/relay'),
	('GET', '/api/v1/instance'),
	('POST', '/api/v1/token')
)


def check_api_path(method: str, path: str) -> bool:
	if path.startswith('/api/doc') or (method, path) in PUBLIC_API_PATHS:
		return False

	return path.startswith('/api')


@web.middleware
async def handle_api_path(request: Request, handler: Callable) -> Response:
	try:
		if (token := request.cookies.get('user-token')):
			request['token'] = token

		else:
			request['token'] = request.headers['Authorization'].replace('Bearer', '').strip()

		with get_app().database.session() as conn:
			request['user'] = conn.get_user_by_token(request['token'])

	except (KeyError, ValueError):
		request['token'] = None
		request['user'] = None

	if request.method != "OPTIONS" and check_api_path(request.method, request.path):
		if not request['token']:
			return Response.new_error(401, 'Missing token', 'json')

		if not request['user']:
			return Response.new_error(401, 'Invalid token', 'json')

	response = await handler(request)

	if request.path.startswith('/api'):
		response.headers['Access-Control-Allow-Origin'] = '*'
		response.headers['Access-Control-Allow-Headers'] = ', '.join(ALLOWED_HEADERS)

	return response


@register_route('/api/v1/token')
class Login(View):
	async def get(self, request: Request) -> Response:
		return Response.new({'message': 'Token valid'}, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['username', 'password'], [])

		if isinstance(data, Response):
			return data

		with self.database.session(True) as conn:
			if not (user := conn.get_user(data['username'])):
				return Response.new_error(401, 'User not found', 'json')

			try:
				conn.hasher.verify(user['hash'], data['password'])

			except VerifyMismatchError:
				return Response.new_error(401, 'Invalid password', 'json')

			token = conn.put_token(data['username'])

		resp = Response.new({'token': token['code']}, ctype = 'json')
		resp.set_cookie(
				'user-token',
				token['code'],
				max_age = 60 * 60 * 24 * 365,
				domain = self.config.domain,
				path = '/',
				secure = True,
				httponly = False,
				samesite = 'lax'
			)

		return resp


	async def delete(self, request: Request) -> Response:
		with self.database.session() as conn:
			conn.del_token(request['token'])

		return Response.new({'message': 'Token revoked'}, ctype = 'json')


@register_route('/api/v1/relay')
class RelayInfo(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			config = conn.get_config_all()
			inboxes = [row['domain'] for row in conn.get_inboxes()]

		data = {
			'domain': self.config.domain,
			'name': config.name,
			'description': config.note,
			'version': __version__,
			'whitelist_enabled': config.whitelist_enabled,
			'email': None,
			'admin': None,
			'icon': None,
			'instances': inboxes
		}

		return Response.new(data, ctype = 'json')


@register_route('/api/v1/config')
class Config(View):
	async def get(self, request: Request) -> Response:
		data = {}

		with self.database.session() as conn:
			for key, value in conn.get_config_all().to_dict().items():
				if key in ConfigData.SYSTEM_KEYS():
					continue

				if key == 'log-level':
					value = value.name

				data[key] = value

		return Response.new(data, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['key', 'value'], [])

		if isinstance(data, Response):
			return data

		data['key'] = data['key'].replace('-', '_')

		if data['key'] not in ConfigData.USER_KEYS():
			return Response.new_error(400, 'Invalid key', 'json')

		with self.database.session() as conn:
			conn.put_config(data['key'], data['value'])

		return Response.new({'message': 'Updated config'}, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['key'], [])

		if isinstance(data, Response):
			return data

		if data['key'] not in ConfigData.USER_KEYS():
			return Response.new_error(400, 'Invalid key', 'json')

		with self.database.session() as conn:
			conn.put_config(data['key'], ConfigData.DEFAULT(data['key']))

		return Response.new({'message': 'Updated config'}, ctype = 'json')


@register_route('/api/v1/instance')
class Inbox(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = conn.get_inboxes()

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
				actor_data: Message | None = await self.client.get(data['actor'], True, Message)

				if actor_data is None:
					return Response.new_error(500, 'Failed to fetch actor', 'json')

				data['inbox'] = actor_data.shared_inbox

			if not data.get('software'):
				nodeinfo = await self.client.fetch_nodeinfo(data['domain'])

				if nodeinfo is not None:
					data['software'] = nodeinfo.sw_name

			row = conn.put_inbox(**data)

		return Response.new(row, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], ['actor', 'software', 'followid'])

			if isinstance(data, Response):
				return data

			if not (instance := conn.get_inbox(data['domain'])):
				return Response.new_error(404, 'Instance with domain not found', 'json')

			instance = conn.put_inbox(instance['domain'], **data)

		return Response.new(instance, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], [])

			if isinstance(data, Response):
				return data

			if not conn.get_inbox(data['domain']):
				return Response.new_error(404, 'Instance with domain not found', 'json')

			conn.del_inbox(data['domain'])

		return Response.new({'message': 'Deleted instance'}, ctype = 'json')


@register_route('/api/v1/request')
class RequestView(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			instances = conn.get_requests()

		return Response.new(instances, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data: dict[str, Any] | Response = await self.get_api_data(['domain', 'accept'], [])
		data['accept'] = boolean(data['accept'])

		try:
			with self.database.session(True) as conn:
				instance = conn.put_request_response(data['domain'], data['accept'])

		except KeyError:
			return Response.new_error(404, 'Request not found', 'json')

		message = Message.new_response(
			host = self.config.domain,
			actor = instance['actor'],
			followid = instance['followid'],
			accept = data['accept']
		)

		self.app.push_message(instance['inbox'], message, instance)

		if data['accept'] and instance['software'] != 'mastodon':
			message = Message.new_follow(
				host = self.config.domain,
				actor = instance['actor']
			)

			self.app.push_message(instance['inbox'], message, instance)

		resp_message = {'message': 'Request accepted' if data['accept'] else 'Request denied'}
		return Response.new(resp_message, ctype = 'json')


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

			ban = conn.update_domain_ban(**data)

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

			ban = conn.update_software_ban(**data)

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


@register_route('/api/v1/user')
class User(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			items = []

			for row in conn.execute('SELECT * FROM users'):
				del row['hash']
				items.append(row)

		return Response.new(items, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['username', 'password'], ['handle'])

		if isinstance(data, Response):
			return data

		with self.database.session() as conn:
			if conn.get_user(data['username']):
				return Response.new_error(404, 'User already exists', 'json')

			user = conn.put_user(**data)
			del user['hash']

		return Response.new(user, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		data = await self.get_api_data(['username'], ['password', 'handle'])

		if isinstance(data, Response):
			return data

		with self.database.session(True) as conn:
			user = conn.put_user(**data)
			del user['hash']

		return Response.new(user, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['username'], [])

		if isinstance(data, Response):
			return data

		with self.database.session(True) as conn:
			if not conn.get_user(data['username']):
				return Response.new_error(404, 'User does not exist', 'json')

			conn.del_user(data['username'])

		return Response.new({'message': 'Deleted user'}, ctype = 'json')


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
