from __future__ import annotations

import typing

from aiohttp import web

from .base import View, register_route

from ..database import THEMES
from ..logger import LogLevel
from ..misc import Response, get_app

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

	if not request.path.startswith('/api') and not request['user'] and request['token']:
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


@register_route('/manifest.json')
class ManifestJson(View):
	async def get(self, request: Request) -> Response:
		with self.database.session(False) as conn:
			config = conn.get_config_all()
			theme = THEMES[config.theme]

		data = {
			'background_color': theme['background'],
			'categories': ['activitypub'],
			'description': 'Message relay for the ActivityPub network',
			'display': 'standalone',
			'name': config['name'],
			'orientation': 'portrait',
			'scope': f"https://{self.config.domain}/",
			'short_name': 'ActivityRelay',
			'start_url': f"https://{self.config.domain}/",
			'theme_color': theme['primary']
		}

		return Response.new(data, ctype = 'webmanifest')


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
