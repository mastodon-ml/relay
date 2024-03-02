from __future__ import annotations

import typing

from aiohttp import web
from argon2.exceptions import VerifyMismatchError

from .base import View, register_route

from ..misc import Response

if typing.TYPE_CHECKING:
	from aiohttp.web import Request


AUTH_ROUTES = {
	'/admin',
	'/admin/instances',
	'/admin/domain_bans',
	'/admin/software_bans',
	'/admin/whitelist',
	'/admin/config',
	'/logout'
}


UNAUTH_ROUTES = {
	'/',
	'/login'
}

ALL_ROUTES = {*AUTH_ROUTES, *UNAUTH_ROUTES}


@web.middleware
async def handle_frontend_path(request: web.Request, handler: Coroutine) -> Response:
	if request.path in ALL_ROUTES:
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
			instances = tuple(conn.execute('SELECT * FROM inboxes').all())

		# text = HOME_TEMPLATE.format(
		# 	host = self.config.domain,
		# 	note = config['note'],
		# 	count = len(inboxes),
		# 	targets = '<br>'.join(inbox['domain'] for inbox in inboxes)
		# )

		data = self.template.render('page/home.haml', self, instances = instances)
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
	async def get(self, request: Request) -> Response:
		data = self.template.render('page/admin-instances.haml', self)
		return Response.new(data, ctype = 'html')


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
	async def get(self, request: Request) -> Response:
		data = self.template.render('page/admin-config.haml', self)
		return Response.new(data, ctype = 'html')


@register_route('/style.css')
class StyleCss(View):
	async def get(self, request: Request) -> Response:
		data = self.template.render('style.css', self, page = request.query.getone('page', ""))
		return Response.new(data, ctype = 'css')
