from aiohttp import web
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import unquote

from .base import View, register_route

from ..database import THEMES
from ..logger import LogLevel
from ..misc import TOKEN_PATHS, Response


@web.middleware
async def handle_frontend_path(
							request: web.Request,
							handler: Callable[[web.Request], Awaitable[Response]]) -> Response:

	if request['user'] is not None and request.path == '/login':
		return Response.new_redir('/')

	if request.path.startswith(TOKEN_PATHS[:2]) and request['user'] is None:
		if request.path == '/logout':
			return Response.new_redir('/')

		response = Response.new_redir(f'/login?redir={request.path}')

		if request['token'] is not None:
			response.del_cookie('user-token')

		return response

	response = await handler(request)

	if not request.path.startswith('/api'):
		if request['user'] is None and request['token'] is not None:
			response.del_cookie('user-token')

	return response


@register_route('/')
class HomeView(View):
	async def get(self, request: web.Request) -> Response:
		with self.database.session() as conn:
			context: dict[str, Any] = {
				'instances': tuple(conn.get_inboxes())
			}

		data = self.template.render('page/home.haml', self.request, **context)
		return Response.new(data, ctype='html')


@register_route('/login')
class Login(View):
	async def get(self, request: web.Request) -> Response:
		redir = unquote(request.query.get('redir', '/'))
		data = self.template.render('page/login.haml', self.request, redir = redir)
		return Response.new(data, ctype = 'html')


@register_route('/logout')
class Logout(View):
	async def get(self, request: web.Request) -> Response:
		with self.database.session(True) as conn:
			conn.del_app(request['token'].client_id, request['token'].client_secret)

		resp = Response.new_redir('/')
		resp.del_cookie('user-token', domain = self.config.domain, path = '/')
		return resp


@register_route('/admin')
class Admin(View):
	async def get(self, request: web.Request) -> Response:
		return Response.new_redir(f'/login?redir={request.path}', 301)


@register_route('/admin/instances')
class AdminInstances(View):
	async def get(self,
				request: web.Request,
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

		data = self.template.render('page/admin-instances.haml', self.request, **context)
		return Response.new(data, ctype = 'html')


@register_route('/admin/whitelist')
class AdminWhitelist(View):
	async def get(self,
				request: web.Request,
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

		data = self.template.render('page/admin-whitelist.haml', self.request, **context)
		return Response.new(data, ctype = 'html')


@register_route('/admin/domain_bans')
class AdminDomainBans(View):
	async def get(self,
				request: web.Request,
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

		data = self.template.render('page/admin-domain_bans.haml', self.request, **context)
		return Response.new(data, ctype = 'html')


@register_route('/admin/software_bans')
class AdminSoftwareBans(View):
	async def get(self,
				request: web.Request,
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

		data = self.template.render('page/admin-software_bans.haml', self.request, **context)
		return Response.new(data, ctype = 'html')


@register_route('/admin/users')
class AdminUsers(View):
	async def get(self,
				request: web.Request,
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

		data = self.template.render('page/admin-users.haml', self.request, **context)
		return Response.new(data, ctype = 'html')


@register_route('/admin/config')
class AdminConfig(View):
	async def get(self, request: web.Request, message: str | None = None) -> Response:
		context: dict[str, Any] = {
			'themes': tuple(THEMES.keys()),
			'levels': tuple(level.name for level in LogLevel),
			'message': message,
			'desc': {
				"name": "Name of the relay to be displayed in the header of the pages and in " +
					"the actor endpoint.", # noqa: E131
				"note": "Description of the relay to be displayed on the front page and as the " +
					"bio in the actor endpoint.",
				"theme": "Color theme to use on the web pages.",
				"log_level": "Minimum level of logging messages to print to the console.",
				"whitelist_enabled": "Only allow instances in the whitelist to be able to follow.",
				"approval_required": "Require instances not on the whitelist to be approved by " +
					"and admin. The `whitelist-enabled` setting is ignored when this is enabled."
			}
		}

		data = self.template.render('page/admin-config.haml', self.request, **context)
		return Response.new(data, ctype = 'html')


@register_route('/manifest.json')
class ManifestJson(View):
	async def get(self, request: web.Request) -> Response:
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
	async def get(self, request: web.Request, theme: str) -> Response:
		try:
			context: dict[str, Any] = {
				'theme': THEMES[theme]
			}

		except KeyError:
			return Response.new('Invalid theme', 404)

		data = self.template.render('variables.css', self.request, **context)
		return Response.new(data, ctype = 'css')
