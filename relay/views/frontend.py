from __future__ import annotations

import typing

from aiohttp import web
from argon2.exceptions import VerifyMismatchError

from .base import View, register_route

from ..database import CONFIG_DEFAULTS, THEMES
from ..logger import LogLevel
from ..misc import ACTOR_FORMATS, Message, Response

if typing.TYPE_CHECKING:
	from aiohttp.web import Request


UNAUTH_ROUTES = {
	'/',
	'/login'
}

CONFIG_IGNORE = (
	'schema-version',
	'private-key'
)


@web.middleware
async def handle_frontend_path(request: web.Request, handler: Coroutine) -> Response:
	if request.path in UNAUTH_ROUTES or request.path.startswith('/admin'):
		request['token'] = request.cookies.get('user-token')
		request['user'] = None

		if request['token']:
			with request.app.database.session(False) as conn:
				request['user'] = conn.get_user_by_token(request['token'])

		if request['user'] and request.path == '/login':
			return Response.new('', 302, {'Location': '/'})

		if not request['user'] and request.path.startswith('/admin'):
			return Response.new('', 302, {'Location': f'/login?redir={request.path}'})

	return await handler(request)


# pylint: disable=unused-argument

@register_route('/')
class HomeView(View):
	async def get(self, request: Request) -> Response:
		with self.database.session() as conn:
			context = {
				'instances': tuple(conn.execute('SELECT * FROM inboxes').all())
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
				httponly = True,
				samesite = 'Strict'
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
			context = {
				'instances': tuple(conn.execute('SELECT * FROM inboxes').all())
			}

			if error:
				context['error'] = error

			if message:
				context['message'] = message

		data = self.template.render('page/admin-instances.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		data = {key: value for key, value in (await request.post()).items()}

		if not data['actor'] and not data['domain']:
			return await self.get(request, error = 'Missing actor and/or domain')

		if not data['domain']:
			data['domain'] = urlparse(data['actor']).netloc

		if not data['software']:
			nodeinfo = await self.client.fetch_nodeinfo(data['domain'])
			data['software'] = nodeinfo.sw_name

		if not data['actor'] and data['software'] in ACTOR_FORMATS:
			data['actor'] = ACTOR_FORMATS[data['software']].format(domain = data['domain'])

		if not data['inbox'] and data['actor']:
			actor = await self.client.get(data['actor'], sign_headers = True, loads = Message.parse)
			data['inbox'] = actor.shared_inbox

		with self.database.session(True) as conn:
			conn.put_inbox(**data)

		return await self.get(request, message = "Added new inbox")


@register_route('/admin/instances/delete/{domain}')
class AdminInstancesDelete(View):
	async def get(self, request: Request, domain: str) -> Response:
		with self.database.session() as conn:
			if not (conn.get_inbox(domain)):
				return await AdminInstances(request).get(request, message = 'Instance not found')

			conn.del_inbox(domain)

		return await AdminInstances(request).get(request, message = 'Removed instance')


@register_route('/admin/whitelist')
class AdminWhitelist(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('page/admin-whitelist.haml', self)
		return Response.new(data, ctype = 'html')


@register_route('/admin/domain_bans')
class AdminDomainBans(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('page/admin-domain_bans.haml', self)
		return Response.new(data, ctype = 'html')


@register_route('/admin/software_bans')
class AdminSoftwareBans(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('page/admin-software_bans.haml', self)
		return Response.new(data, ctype = 'html')


@register_route('/admin/config')
class AdminConfig(View):
	async def get(self, request: Request, message: str | None = None) -> Response:
		context = {
			'themes': tuple(THEMES.keys()),
			'LogLevel': LogLevel,
			'message': message
		}
		data = self.template.render('page/admin-config.haml', self, **context)
		return Response.new(data, ctype = 'html')


	async def post(self, request: Request) -> Response:
		form = dict(await request.post())

		with self.database.session(True) as conn:
			for key in CONFIG_DEFAULTS:
				value = form.get(key)

				if key == 'whitelist-enabled':
					value = bool(value)

				elif key.lower() in CONFIG_IGNORE:
					continue

				if value is None:
					continue

				conn.put_config(key, value)

		return await self.get(request, message = 'Updated config')


@register_route('/style.css')
class StyleCss(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('style.css', self, page = request.query.getone('page', ""))
		return Response.new(data, ctype = 'css')
