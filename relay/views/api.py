import traceback

from aiohttp.web import Request, middleware
from argon2.exceptions import VerifyMismatchError
from blib import HttpError, convert_to_boolean
from collections.abc import Awaitable, Callable, Sequence
from urllib.parse import urlparse

from .base import View, register_route

from .. import __version__
from ..database import ConfigData, schema
from ..misc import Message, Response


DEFAULT_REDIRECT: str = 'urn:ietf:wg:oauth:2.0:oob'
ALLOWED_HEADERS: set[str] = {
	'accept',
	'authorization',
	'content-type'
}

PUBLIC_API_PATHS: Sequence[tuple[str, str]] = (
	('GET', '/api/v1/relay'),
	('POST', '/api/v1/app'),
	('POST', '/api/v1/login'),
	('POST', '/api/v1/token')
)


def check_api_path(method: str, path: str) -> bool:
	if path.startswith('/api/doc') or (method, path) in PUBLIC_API_PATHS:
		return False

	return path.startswith('/api')


@middleware
async def handle_api_path(
						request: Request,
						handler: Callable[[Request], Awaitable[Response]]) -> Response:

	if not request.path.startswith('/api') or request.path == '/api/doc':
		return await handler(request)

	if request.method != "OPTIONS" and check_api_path(request.method, request.path):
		if request['token'] is None:
			raise HttpError(401, 'Missing token')

		if request['user'] is None:
			raise HttpError(401, 'Invalid token')

	response = await handler(request)
	response.headers['Access-Control-Allow-Origin'] = '*'
	response.headers['Access-Control-Allow-Headers'] = ', '.join(ALLOWED_HEADERS)

	return response


@register_route('/oauth/authorize')
@register_route('/api/oauth/authorize')
class OauthAuthorize(View):
	async def get(self, request: Request) -> Response:
		data = await self.get_api_data(['response_type', 'client_id', 'redirect_uri'], [])

		if data['response_type'] != 'code':
			raise HttpError(400, 'Response type is not "code"')

		with self.database.session(True) as conn:
			with conn.select('apps', client_id = data['client_id']) as cur:
				if (app := cur.one(schema.App)) is None:
					raise HttpError(404, 'Could not find app')

		if app.token is not None:
			raise HttpError(400, 'Application has already been authorized')

		if app.auth_code is not None:
			context = {'application': app}
			html = self.template.render(
				'page/authorize_show.haml', self.request, **context
			)

			return Response.new(html, ctype = 'html')

		if data['redirect_uri'] != app.redirect_uri:
			raise HttpError(400, 'redirect_uri does not match application')

		context = {'application': app}
		html = self.template.render('page/authorize_new.haml', self.request, **context)
		return Response.new(html, ctype = 'html')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(
			['client_id', 'client_secret', 'redirect_uri', 'response'], []
		)

		with self.database.session(True) as conn:
			if (app := conn.get_app(data['client_id'], data['client_secret'])) is None:
				raise HttpError(404, 'Could not find app')

			if convert_to_boolean(data['response']):
				if app.token is not None:
					raise HttpError(400, 'Application has already been authorized')

				if app.auth_code is None:
					app = conn.update_app(app, request['user'], True)

				if app.redirect_uri == DEFAULT_REDIRECT:
					context = {'application': app}
					html = self.template.render(
						'page/authorize_show.haml', self.request, **context
					)

					return Response.new(html, ctype = 'html')

				return Response.new_redir(f'{app.redirect_uri}?code={app.auth_code}')

			if not conn.del_app(app.client_id, app.client_secret):
				raise HttpError(404, 'App not found')

			return Response.new_redir('/')


@register_route('/oauth/token')
@register_route('/api/oauth/token')
class OauthToken(View):
	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(
			['grant_type', 'code', 'client_id', 'client_secret', 'redirect_uri'], []
		)

		if data['grant_type'] != 'authorization_code':
			raise HttpError(400, 'Invalid grant type')

		with self.database.session(True) as conn:
			if (app := conn.get_app(data['client_id'], data['client_secret'])) is None:
				raise HttpError(404, 'Application not found')

			if app.auth_code != data['code']:
				raise HttpError(400, 'Invalid authentication code')

			if app.redirect_uri != data['redirect_uri']:
				raise HttpError(400, 'Invalid redirect uri')

			app = conn.update_app(app, request['user'], False)

		return Response.new(app.get_api_data(True), ctype = 'json')


@register_route('/oauth/revoke')
@register_route('/api/oauth/revoke')
class OauthRevoke(View):
	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['client_id', 'client_secret', 'token'], [])

		with self.database.session(True) as conn:
			if (app := conn.get_app(**data)) is None:
				raise HttpError(404, 'Could not find token')

			if app.user != request['token'].username:
				raise HttpError(403, 'Invalid token')

			if not conn.del_app(**data):
				raise HttpError(400, 'Token not removed')

			return Response.new({'msg': 'Token deleted'}, ctype = 'json')


@register_route('/api/v1/app')
class App(View):
	async def get(self, request: Request) -> Response:
		return Response.new(request['token'].get_api_data(), ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['name', 'redirect_uri'], ['website'])

		with self.database.session(True) as conn:
			app = conn.put_app(
				name = data['name'],
				redirect_uri = data['redirect_uri'],
				website = data.get('website')
			)

		return Response.new(app.get_api_data(), ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['client_id', 'client_secret'], [])

		with self.database.session(True) as conn:
			if not conn.del_app(data['client_id'], data['client_secret'], request['token'].code):
				raise HttpError(400, 'Token not removed')

			return Response.new({'msg': 'Token deleted'}, ctype = 'json')


@register_route('/api/v1/login')
class Login(View):
	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['username', 'password'], [])

		with self.database.session(True) as conn:
			if not (user := conn.get_user(data['username'])):
				raise HttpError(401, 'User not found')

			try:
				conn.hasher.verify(user['hash'], data['password'])

			except VerifyMismatchError:
				raise HttpError(401, 'Invalid password')

			app = conn.put_app_login(user)

		resp = Response.new(app.get_api_data(True), ctype = 'json')
		resp.set_cookie(
				'user-token',
				app.token, # type: ignore[arg-type]
				max_age = 60 * 60 * 24 * 365,
				domain = self.config.domain,
				path = '/',
				secure = True,
				httponly = False,
				samesite = 'lax'
			)

		return resp


@register_route('/api/v1/relay')
class RelayInfo(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			config = conn.get_config_all()
			inboxes = [row.domain for row in conn.get_inboxes()]

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
		data['key'] = data['key'].replace('-', '_')

		if data['key'] not in ConfigData.USER_KEYS():
			raise HttpError(400, 'Invalid key')

		with self.database.session() as conn:
			value = conn.put_config(data['key'], data['value'])

		if data['key'] == 'log-level':
			self.app.workers.set_log_level(value)

		return Response.new({'message': 'Updated config'}, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['key'], [])

		if data['key'] not in ConfigData.USER_KEYS():
			raise HttpError(400, 'Invalid key')

		with self.database.session() as conn:
			value = conn.put_config(data['key'], ConfigData.DEFAULT(data['key']))

		if data['key'] == 'log-level':
			self.app.workers.set_log_level(value)

		return Response.new({'message': 'Updated config'}, ctype = 'json')


@register_route('/api/v1/instance')
class Inbox(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = tuple(conn.get_inboxes())

		return Response.new(data, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['actor'], ['inbox', 'software', 'followid'])
		data['domain'] = urlparse(data["actor"]).netloc

		with self.database.session() as conn:
			if conn.get_inbox(data['domain']) is not None:
				raise HttpError(404, 'Instance already in database')

			data['domain'] = data['domain'].encode('idna').decode()

			if not data.get('inbox'):
				try:
					actor_data = await self.client.get(data['actor'], True, Message)

				except Exception:
					traceback.print_exc()
					raise HttpError(500, 'Failed to fetch actor') from None

				data['inbox'] = actor_data.shared_inbox

			if not data.get('software'):
				try:
					nodeinfo = await self.client.fetch_nodeinfo(data['domain'])
					data['software'] = nodeinfo.sw_name

				except Exception:
					pass

			row = conn.put_inbox(
				domain = data['domain'],
				actor = data['actor'],
				inbox = data.get('inbox'),
				software = data.get('software'),
				followid = data.get('followid')
			)

		return Response.new(row, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], ['actor', 'software', 'followid'])
			data['domain'] = data['domain'].encode('idna').decode()

			if (instance := conn.get_inbox(data['domain'])) is None:
				raise HttpError(404, 'Instance with domain not found')

			instance = conn.put_inbox(
				instance.domain,
				actor = data.get('actor'),
				software = data.get('software'),
				followid = data.get('followid')
			)

		return Response.new(instance, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], [])
			data['domain'] = data['domain'].encode('idna').decode()

			if not conn.get_inbox(data['domain']):
				raise HttpError(404, 'Instance with domain not found')

			conn.del_inbox(data['domain'])

		return Response.new({'message': 'Deleted instance'}, ctype = 'json')


@register_route('/api/v1/request')
class RequestView(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			instances = tuple(conn.get_requests())

		return Response.new(instances, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['domain', 'accept'], [])
		data['domain'] = data['domain'].encode('idna').decode()

		try:
			with self.database.session(True) as conn:
				instance = conn.put_request_response(
					data['domain'],
					convert_to_boolean(data['accept'])
				)

		except KeyError:
			raise HttpError(404, 'Request not found') from None

		message = Message.new_response(
			host = self.config.domain,
			actor = instance.actor,
			followid = instance.followid,
			accept = convert_to_boolean(data['accept'])
		)

		self.app.push_message(instance.inbox, message, instance)

		if data['accept'] and instance.software != 'mastodon':
			message = Message.new_follow(
				host = self.config.domain,
				actor = instance.actor
			)

			self.app.push_message(instance.inbox, message, instance)

		resp_message = {'message': 'Request accepted' if data['accept'] else 'Request denied'}
		return Response.new(resp_message, ctype = 'json')


@register_route('/api/v1/domain_ban')
class DomainBan(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			bans = tuple(conn.get_domain_bans())

		return Response.new(bans, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['domain'], ['note', 'reason'])
		data['domain'] = data['domain'].encode('idna').decode()

		with self.database.session() as conn:
			if conn.get_domain_ban(data['domain']) is not None:
				raise HttpError(400, 'Domain already banned')

			ban = conn.put_domain_ban(
				domain = data['domain'],
				reason = data.get('reason'),
				note = data.get('note')
			)

		return Response.new(ban, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], ['note', 'reason'])

			if not any([data.get('note'), data.get('reason')]):
				raise HttpError(400, 'Must include note and/or reason parameters')

			data['domain'] = data['domain'].encode('idna').decode()

			if conn.get_domain_ban(data['domain']) is None:
				raise HttpError(404, 'Domain not banned')

			ban = conn.update_domain_ban(
				domain = data['domain'],
				reason = data.get('reason'),
				note = data.get('note')
			)

		return Response.new(ban, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		with self.database.session() as conn:
			data = await self.get_api_data(['domain'], [])
			data['domain'] = data['domain'].encode('idna').decode()

			if conn.get_domain_ban(data['domain']) is None:
				raise HttpError(404, 'Domain not banned')

			conn.del_domain_ban(data['domain'])

		return Response.new({'message': 'Unbanned domain'}, ctype = 'json')


@register_route('/api/v1/software_ban')
class SoftwareBan(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			bans = tuple(conn.get_software_bans())

		return Response.new(bans, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['name'], ['note', 'reason'])

		with self.database.session() as conn:
			if conn.get_software_ban(data['name']) is not None:
				raise HttpError(400, 'Domain already banned')

			ban = conn.put_software_ban(
				name = data['name'],
				reason = data.get('reason'),
				note = data.get('note')
			)

		return Response.new(ban, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		data = await self.get_api_data(['name'], ['note', 'reason'])

		if not any([data.get('note'), data.get('reason')]):
			raise HttpError(400, 'Must include note and/or reason parameters')

		with self.database.session() as conn:
			if conn.get_software_ban(data['name']) is None:
				raise HttpError(404, 'Software not banned')

			ban = conn.update_software_ban(
				name = data['name'],
				reason = data.get('reason'),
				note = data.get('note')
			)

		return Response.new(ban, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['name'], [])

		with self.database.session() as conn:
			if conn.get_software_ban(data['name']) is None:
				raise HttpError(404, 'Software not banned')

			conn.del_software_ban(data['name'])

		return Response.new({'message': 'Unbanned software'}, ctype = 'json')


@register_route('/api/v1/user')
class User(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			items = []

			for row in conn.get_users():
				del row['hash']
				items.append(row)

		return Response.new(items, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['username', 'password'], ['handle'])

		with self.database.session() as conn:
			if conn.get_user(data['username']) is not None:
				raise HttpError(404, 'User already exists')

			user = conn.put_user(
				username = data['username'],
				password = data['password'],
				handle = data.get('handle')
			)

		del user['hash']
		return Response.new(user, ctype = 'json')


	async def patch(self, request: Request) -> Response:
		data = await self.get_api_data(['username'], ['password', 'handle'])

		with self.database.session(True) as conn:
			user = conn.put_user(
				username = data['username'],
				password = data['password'],
				handle = data.get('handle')
			)

		del user['hash']
		return Response.new(user, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['username'], [])

		with self.database.session(True) as conn:
			if conn.get_user(data['username']) is None:
				raise HttpError(404, 'User does not exist')

			conn.del_user(data['username'])

		return Response.new({'message': 'Deleted user'}, ctype = 'json')


@register_route('/api/v1/whitelist')
class Whitelist(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			items = tuple(conn.get_domains_whitelist())

		return Response.new(items, ctype = 'json')


	async def post(self, request: Request) -> Response:
		data = await self.get_api_data(['domain'], [])

		domain = data['domain'].encode('idna').decode()

		with self.database.session() as conn:
			if conn.get_domain_whitelist(domain) is not None:
				raise HttpError(400, 'Domain already added to whitelist')

			item = conn.put_domain_whitelist(domain)

		return Response.new(item, ctype = 'json')


	async def delete(self, request: Request) -> Response:
		data = await self.get_api_data(['domain'], [])

		domain = data['domain'].encode('idna').decode()

		with self.database.session() as conn:
			if conn.get_domain_whitelist(domain) is None:
				raise HttpError(404, 'Domain not in whitelist')

			conn.del_domain_whitelist(domain)

		return Response.new({'message': 'Removed domain from whitelist'}, ctype = 'json')
