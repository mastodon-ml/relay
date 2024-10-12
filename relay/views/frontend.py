from __future__ import annotations

from aiohttp.web import Request, middleware
from blib import HttpMethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from .base import register_route

from ..database import THEMES
from ..logger import LogLevel
from ..misc import TOKEN_PATHS, Response

if TYPE_CHECKING:
	from ..application import Application


@middleware
async def handle_frontend_path(
							request: Request,
							handler: Callable[[Request], Awaitable[Response]]) -> Response:

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


@register_route(HttpMethod.GET, "/")
async def handle_home(app: Application, request: Request) -> Response:
	with app.database.session() as conn:
		context: dict[str, Any] = {
			'instances': tuple(conn.get_inboxes())
		}

	return Response.new_template(200, "page/home.haml", request, context)


@register_route(HttpMethod.GET, '/login')
async def handle_login(app: Application, request: Request) -> Response:
	context = {"redir": unquote(request.query.get("redir", "/"))}
	return Response.new_template(200, "page/login.haml", request, context)


@register_route(HttpMethod.GET, '/logout')
async def handle_logout(app: Application, request: Request) -> Response:
	with app.database.session(True) as conn:
		conn.del_app(request['token'].client_id, request['token'].client_secret)

	resp = Response.new_redir('/')
	resp.del_cookie('user-token', domain = app.config.domain, path = '/')
	return resp


@register_route(HttpMethod.GET, '/admin')
async def handle_admin(app: Application, request: Request) -> Response:
	return Response.new_redir(f'/login?redir={request.path}', 301)


@register_route(HttpMethod.GET, '/admin/instances')
async def handle_admin_instances(
								app: Application,
								request: Request,
								error: str | None = None,
								message: str | None = None) -> Response:

	with app.database.session() as conn:
		context: dict[str, Any] = {
			'instances': tuple(conn.get_inboxes()),
			'requests': tuple(conn.get_requests())
		}

		if error:
			context['error'] = error

		if message:
			context['message'] = message

	return Response.new_template(200, "page/admin-instances.haml", request, context)


@register_route(HttpMethod.GET, '/admin/whitelist')
async def handle_admin_whitelist(
								app: Application,
								request: Request,
								error: str | None = None,
								message: str | None = None) -> Response:

	with app.database.session() as conn:
		context: dict[str, Any] = {
			'whitelist': tuple(conn.execute('SELECT * FROM whitelist ORDER BY domain ASC'))
		}

		if error:
			context['error'] = error

		if message:
			context['message'] = message

	return Response.new_template(200, "page/admin-whitelist.haml", request, context)


@register_route(HttpMethod.GET, '/admin/domain_bans')
async def handle_admin_instance_bans(
							app: Application,
							request: Request,
							error: str | None = None,
							message: str | None = None) -> Response:

	with app.database.session() as conn:
		context: dict[str, Any] = {
			'bans': tuple(conn.execute('SELECT * FROM domain_bans ORDER BY domain ASC'))
		}

		if error:
			context['error'] = error

		if message:
			context['message'] = message

	return Response.new_template(200, "page/admin-domain_bans.haml", request, context)


@register_route(HttpMethod.GET, '/admin/software_bans')
async def handle_admin_software_bans(
									app: Application,
									request: Request,
									error: str | None = None,
									message: str | None = None) -> Response:

	with app.database.session() as conn:
		context: dict[str, Any] = {
			'bans': tuple(conn.execute('SELECT * FROM software_bans ORDER BY name ASC'))
		}

		if error:
			context['error'] = error

		if message:
			context['message'] = message

	return Response.new_template(200, "page/admin-software_bans.haml", request, context)


@register_route(HttpMethod.GET, '/admin/users')
async def handle_admin_users(
							app: Application,
							request: Request,
							error: str | None = None,
							message: str | None = None) -> Response:

	with app.database.session() as conn:
		context: dict[str, Any] = {
			'users': tuple(conn.execute('SELECT * FROM users ORDER BY username ASC'))
		}

		if error:
			context['error'] = error

		if message:
			context['message'] = message

	return Response.new_template(200, "page/admin-users.haml", request, context)


@register_route(HttpMethod.GET, '/admin/config')
async def handle_admin_config(
							app: Application,
							request: Request,
							message: str | None = None) -> Response:

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

	return Response.new_template(200, "page/admin-config.haml", request, context)


@register_route(HttpMethod.GET, '/manifest.json')
async def handle_manifest(app: Application, request: Request) -> Response:
	with app.database.session(False) as conn:
		config = conn.get_config_all()
		theme = THEMES[config.theme]

	data = {
		'background_color': theme['background'],
		'categories': ['activitypub'],
		'description': 'Message relay for the ActivityPub network',
		'display': 'standalone',
		'name': config['name'],
		'orientation': 'portrait',
		'scope': f"https://{app.config.domain}/",
		'short_name': 'ActivityRelay',
		'start_url': f"https://{app.config.domain}/",
		'theme_color': theme['primary']
	}

	return Response.new(data, ctype = 'webmanifest')


@register_route(HttpMethod.GET, '/theme/{theme}.css') # type: ignore[arg-type]
async def handle_theme(app: Application, request: Request, theme: str) -> Response:
	try:
		context: dict[str, Any] = {
			'theme': THEMES[theme]
		}

	except KeyError:
		return Response.new('Invalid theme', 404)

	return Response.new_template(200, "variables.css", request, context, ctype = "css")
