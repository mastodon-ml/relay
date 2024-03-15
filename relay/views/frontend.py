from __future__ import annotations

import typing

from aiohttp import web
from argon2.exceptions import VerifyMismatchError
from urllib.parse import urlparse

from .base import View, register_route

from ..database import THEMES, ConfigData
from ..logger import LogLevel
from ..misc import ACTOR_FORMATS, Message, Response, get_app

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from collections.abc import Callable
	from typing import Any


UNAUTH_ROUTES = {
	'/',
	'/login'
}


@web.middleware
async def handle_frontend_path(request: web.Request, handler: Callable) -> Response:
	app = get_app()

	if request.path in UNAUTH_ROUTES or request.path.startswith('/admin'):
		request['token'] = request.cookies.get('user-token')
		request['user'] = None

		if request['token']:
			with app.database.session(False) as conn:
				request['user'] = conn.get_user_by_token(request['token'])

		if request['user'] and request.path == '/login':
			return Response.new('', 302, {'Location': '/'})

		if not request['user'] and request.path.startswith('/admin'):
				response = Response.new('', 302, {'Location': f'/login?redir={request.path}'})
				response.del_cookie('user-token')
				return response

	response = await handler(request)

	if not request['user'] and request['token']:
		print("del token")
		response.del_cookie('user-token')

	return response


@register_route('/')
class HomeView(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			context: dict[str, Any] = {
				'instances': tuple(conn.get_inboxes())
			}

		data = self.template.render('page/home.haml', self, **context)
		return Response.new(data, ctype='html')


@register_route('/login')
class Login(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('page/login.haml', self)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		form = await request.post()
		params = {}

		with self.database.session(True) as conn:
			if not (user := conn.get_user(form['username'])):
				params = {
					'username': form['username'],
					'error': 'User not found'
				}

			else:
				try:
					conn.hasher.verify(user['hash'], form['password'])

				except VerifyMismatchError:
					params = {
						'username': form['username'],
						'error': 'Invalid password'
					}

			if params:
				data = self.template.render('page/login.haml', self, **params)
				return Response.new(data, ctype = 'html')

			token = conn.put_token(user['username'])
			resp = Response.new_redir(request.query.getone('redir', '/'))
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


@register_route('/logout')
class Logout(View):
	async def get(self, request: Request) -> Response:
		with self.database.session(True) as conn:
			conn.del_token(request['token'])

		resp = Response.new_redir('/')
		resp.del_cookie('user-token', domain = self.config.domain, path = '/')
		return resp


@register_route('/admin')
class Admin(View):
	async def get(self, request: Request) -> Response:
		return Response.new('', 302, {'Location': '/admin/instances'})


@register_route('/admin/instances')
class AdminInstances(View):
	async def get(self,
				request: Request,
				error: str | None = None,
				message: str | None = None) -> Response:

		with self.database.session() as conn:
			context: dict[str, Any] = {
				'instances': tuple(conn.get_inboxes()),
				'requests': tuple(conn.get_requests())
			}

			if error:
				context['error'] = error

			if message:
				context['message'] = message

		data = self.template.render('page/admin-instances.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		post = await request.post()
		data: dict[str, str] = {key: value for key, value in post.items()} # type: ignore

		if not data.get('actor') and not data.get('domain'):
			return await self.get(request, error = 'Missing actor and/or domain')

		if not data.get('domain'):
			data['domain'] = urlparse(data['actor']).netloc

		if not data.get('software'):
			nodeinfo = await self.client.fetch_nodeinfo(data['domain'])

			if nodeinfo is None:
				return await self.get(request, error = 'Failed to fetch nodeinfo')

			data['software'] = nodeinfo.sw_name

		if not data.get('actor') and data['software'] in ACTOR_FORMATS:
			data['actor'] = ACTOR_FORMATS[data['software']].format(domain = data['domain'])

		if not data.get('inbox') and data['actor']:
			actor: Message | None = await self.client.get(data['actor'], True, Message)

			if actor is None:
				return await self.get(request, error = 'Failed to fetch actor')

			data['inbox'] = actor.shared_inbox

		with self.database.session(True) as conn:
			conn.put_inbox(**data)

		return await self.get(request, message = "Added new inbox")


@register_route('/admin/instances/delete/{domain}')
class AdminInstancesDelete(View):
	async def get(self, request: Request, domain: str) -> Response:
		with self.database.session(True) as conn:
			if not conn.get_inbox(domain):
				return await AdminInstances(request).get(request, error = 'Instance not found')

			conn.del_inbox(domain)

		return await AdminInstances(request).get(request, message = 'Removed instance')


@register_route('/admin/instances/approve/{domain}')
class AdminInstancesApprove(View):
	async def get(self, request: Request, domain: str) -> Response:
		try:
			with self.database.session(True) as conn:
				instance = conn.put_request_response(domain, True)

		except KeyError:
			return await AdminInstances(request).get(request, error = 'Instance not found')

		message = Message.new_response(
			host = self.config.domain,
			actor = instance['actor'],
			followid = instance['followid'],
			accept = True
		)

		self.app.push_message(instance['inbox'], message, instance)

		if instance['software'] != 'mastodon':
			message = Message.new_follow(
				host = self.config.domain,
				actor = instance['actor']
			)

			self.app.push_message(instance['inbox'], message, instance)

		return await AdminInstances(request).get(request, message = 'Request accepted')


@register_route('/admin/instances/deny/{domain}')
class AdminInstancesDeny(View):
	async def get(self, request: Request, domain: str) -> Response:
		try:
			with self.database.session(True) as conn:
				instance = conn.put_request_response(domain, False)

		except KeyError:
			return await AdminInstances(request).get(request, error = 'Instance not found')

		message = Message.new_response(
			host = self.config.domain,
			actor = instance['actor'],
			followid = instance['followid'],
			accept = False
		)

		self.app.push_message(instance['inbox'], message, instance)
		return await AdminInstances(request).get(request, message = 'Request denied')


@register_route('/admin/whitelist')
class AdminWhitelist(View):
	async def get(self,
				request: Request,
				error: str | None = None,
				message: str | None = None) -> Response:

		with self.database.session() as conn:
			context: dict[str, Any] = {
				'whitelist': tuple(conn.execute('SELECT * FROM whitelist ORDER BY domain ASC'))
			}

			if error:
				context['error'] = error

			if message:
				context['message'] = message

		data = self.template.render('page/admin-whitelist.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		data = await request.post()

		if not data['domain']:
			return await self.get(request, error = 'Missing domain')

		with self.database.session(True) as conn:
			if conn.get_domain_whitelist(data['domain']):
				return await self.get(request, error = "Domain already in whitelist")

			conn.put_domain_whitelist(data['domain'])

		return await self.get(request, message = "Added/updated domain ban")


@register_route('/admin/whitelist/delete/{domain}')
class AdminWhitlistDelete(View):
	async def get(self, request: Request, domain: str) -> Response:
		with self.database.session() as conn:
			if not conn.get_domain_whitelist(domain):
				msg = 'Whitelisted domain not found'
				return await AdminWhitelist.run("GET", request, error = msg)

			conn.del_domain_whitelist(domain)

		return await AdminWhitelist.run("GET", request, message = 'Removed domain from whitelist')


@register_route('/admin/domain_bans')
class AdminDomainBans(View):
	async def get(self,
				request: Request,
				error: str | None = None,
				message: str | None = None) -> Response:

		with self.database.session() as conn:
			context: dict[str, Any] = {
				'bans': tuple(conn.execute('SELECT * FROM domain_bans ORDER BY domain ASC'))
			}

			if error:
				context['error'] = error

			if message:
				context['message'] = message

		data = self.template.render('page/admin-domain_bans.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		data = await request.post()

		if not data['domain']:
			return await self.get(request, error = 'Missing domain')

		with self.database.session(True) as conn:
			if conn.get_domain_ban(data['domain']):
				conn.update_domain_ban(
					data['domain'],
					data.get('reason'),
					data.get('note')
				)

			else:
				conn.put_domain_ban(
					data['domain'],
					data.get('reason'),
					data.get('note')
				)

		return await self.get(request, message = "Added/updated domain ban")


@register_route('/admin/domain_bans/delete/{domain}')
class AdminDomainBansDelete(View):
	async def get(self, request: Request, domain: str) -> Response:
		with self.database.session() as conn:
			if not conn.get_domain_ban(domain):
				return await AdminDomainBans.run("GET", request, error = 'Domain ban not found')

			conn.del_domain_ban(domain)

		return await AdminDomainBans.run("GET", request, message = 'Unbanned domain')


@register_route('/admin/software_bans')
class AdminSoftwareBans(View):
	async def get(self,
				request: Request,
				error: str | None = None,
				message: str | None = None) -> Response:

		with self.database.session() as conn:
			context: dict[str, Any] = {
				'bans': tuple(conn.execute('SELECT * FROM software_bans ORDER BY name ASC'))
			}

			if error:
				context['error'] = error

			if message:
				context['message'] = message

		data = self.template.render('page/admin-software_bans.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		data = await request.post()

		if not data['name']:
			return await self.get(request, error = 'Missing name')

		with self.database.session(True) as conn:
			if conn.get_software_ban(data['name']):
				conn.update_software_ban(
					data['name'],
					data.get('reason'),
					data.get('note')
				)

			else:
				conn.put_software_ban(
					data['name'],
					data.get('reason'),
					data.get('note')
				)

		return await self.get(request, message = "Added/updated software ban")


@register_route('/admin/software_bans/delete/{name}')
class AdminSoftwareBansDelete(View):
	async def get(self, request: Request, name: str) -> Response:
		with self.database.session() as conn:
			if not conn.get_software_ban(name):
				return await AdminSoftwareBans.run("GET", request, error = 'Software ban not found')

			conn.del_software_ban(name)

		return await AdminSoftwareBans.run("GET", request, message = 'Unbanned software')


@register_route('/admin/users')
class AdminUsers(View):
	async def get(self,
				request: Request,
				error: str | None = None,
				message: str | None = None) -> Response:

		with self.database.session() as conn:
			context: dict[str, Any] = {
				'users': tuple(conn.execute('SELECT * FROM users ORDER BY username ASC'))
			}

			if error:
				context['error'] = error

			if message:
				context['message'] = message

		data = self.template.render('page/admin-users.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		data = await request.post()
		required_fields = {'username', 'password', 'password2'}

		if not all(data.get(field) for field in required_fields):
			return await self.get(request, error = 'Missing username and/or password')

		if data['password'] != data['password2']:
			return await self.get(request, error = 'Passwords do not match')

		with self.database.session(True) as conn:
			if conn.get_user(data['username']):
				return await self.get(request, error = "User already exists")

			conn.put_user(data['username'], data['password'], data['handle'])

		return await self.get(request, message = "Added user")


@register_route('/admin/users/delete/{name}')
class AdminUsersDelete(View):
	async def get(self, request: Request, name: str) -> Response:
		with self.database.session() as conn:
			if not conn.get_user(name):
				return await AdminUsers.run("GET", request, error = 'User not found')

			conn.del_user(name)

		return await AdminUsers.run("GET", request, message = 'User deleted')


@register_route('/admin/config')
class AdminConfig(View):
	async def get(self, request: Request, message: str | None = None) -> Response:
		context: dict[str, Any] = {
			'themes': tuple(THEMES.keys()),
			'levels': tuple(level.name for level in LogLevel),
			'message': message
		}

		data = self.template.render('page/admin-config.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		form = dict(await request.post())
		data = ConfigData()

		for key in ConfigData.USER_KEYS():
			data.set(key, form.get(key.replace('_', '-')))

		with self.database.session(True) as conn:
			for key, value in data.to_dict().items():
				if key in ConfigData.SYSTEM_KEYS():
					continue

				conn.put_config(key, value)

		return await self.get(request, message = 'Updated config')


@register_route('/style.css')
class StyleCss(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('style.css', self)
		return Response.new(data, ctype = 'css')


@register_route('/theme/{theme}.css')
class ThemeCss(View):
	async def get(self, request: Request, theme: str) -> Response:
		try:
			context: dict[str, Any] = {
				'theme': THEMES[theme]
			}

		except KeyError:
			return Response.new('Invalid theme', 404)

		data = self.template.render('variables.css', self, **context)
		return Response.new(data, ctype = 'css')
