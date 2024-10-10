from __future__ import annotations

import asyncio
import multiprocessing
import signal
import time
import traceback

from Crypto.Random import get_random_bytes
from aiohttp import web
from aiohttp.web import HTTPException, StaticResource
from aiohttp_swagger import setup_swagger
from aputils.signer import Signer
from base64 import b64encode
from blib import File, HttpError, port_check
from bsql import Database
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from mimetypes import guess_type
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast

from . import logger as logging
from .cache import Cache, get_cache
from .config import Config
from .database import Connection, get_database
from .database.schema import Instance
from .http_client import HttpClient
from .misc import JSON_PATHS, TOKEN_PATHS, Message, Response
from .template import Template
from .views import VIEWS
from .views.api import handle_api_path
from .views.frontend import handle_frontend_path
from .workers import PushWorkers


def get_csp(request: web.Request) -> str:
	data = [
		"default-src 'self'",
		f"script-src 'nonce-{request['hash']}'",
		f"style-src 'self' 'nonce-{request['hash']}'",
		"form-action 'self'",
		"connect-src 'self'",
		"img-src 'self'",
		"object-src 'none'",
		"frame-ancestors 'none'",
		f"manifest-src 'self' https://{request.app['config'].domain}"
	]

	return '; '.join(data) + ';'


class Application(web.Application):
	DEFAULT: Application | None = None


	def __init__(self, cfgpath: Path | None, dev: bool = False):
		web.Application.__init__(self,
			middlewares = [
				handle_response_headers, # type: ignore[list-item]
				handle_frontend_path, # type: ignore[list-item]
				handle_api_path # type: ignore[list-item]
			]
		)

		Application.DEFAULT = self

		self['running'] = False
		self['signer'] = None
		self['start_time'] = None
		self['cleanup_thread'] = None
		self['dev'] = dev

		self['config'] = Config(cfgpath, load = True)
		self['database'] = get_database(self.config)
		self['client'] = HttpClient()
		self['cache'] = get_cache(self)
		self['cache'].setup()
		self['template'] = Template(self)
		self['push_queue'] = multiprocessing.Queue()
		self['workers'] = PushWorkers(self.config.workers)

		self.cache.setup()
		self.on_cleanup.append(handle_cleanup) # type: ignore

		for path, view in VIEWS:
			self.router.add_view(path, view)

		setup_swagger(
			self,
			ui_version = 3,
			swagger_from_file = File.from_resource('relay', 'data/swagger.yaml')
		)


	@property
	def cache(self) -> Cache:
		return cast(Cache, self['cache'])


	@property
	def client(self) -> HttpClient:
		return cast(HttpClient, self['client'])


	@property
	def config(self) -> Config:
		return cast(Config, self['config'])


	@property
	def database(self) -> Database[Connection]:
		return cast(Database[Connection], self['database'])


	@property
	def signer(self) -> Signer:
		return cast(Signer, self['signer'])


	@signer.setter
	def signer(self, value: Signer | str) -> None:
		if isinstance(value, Signer):
			self['signer'] = value
			return

		self['signer'] = Signer(value, self.config.keyid)


	@property
	def template(self) -> Template:
		return cast(Template, self['template'])


	@property
	def uptime(self) -> timedelta:
		if not self['start_time']:
			return timedelta(seconds=0)

		uptime = datetime.now() - self['start_time']

		return timedelta(seconds=uptime.seconds)


	@property
	def workers(self) -> PushWorkers:
		return cast(PushWorkers, self['workers'])


	def push_message(self, inbox: str, message: Message, instance: Instance) -> None:
		self['workers'].push_message(inbox, message, instance)


	def register_static_routes(self) -> None:
		if self['dev']:
			static = StaticResource('/static', File.from_resource('relay', 'frontend/static'))

		else:
			static = CachedStaticResource(
				'/static', Path(File.from_resource('relay', 'frontend/static'))
			)

		self.router.register_resource(static)


	def run(self) -> None:
		if self["running"]:
			return

		domain = self.config.domain
		host = self.config.listen
		port = self.config.port

		if port_check(port, '127.0.0.1' if host == '0.0.0.0' else host):
			logging.error(f'A server is already running on {host}:{port}')
			return

		self.register_static_routes()

		logging.info(f'Starting webserver at {domain} ({host}:{port})')
		asyncio.run(self.handle_run())


	def set_signal_handler(self, startup: bool) -> None:
		for sig in ('SIGHUP', 'SIGINT', 'SIGQUIT', 'SIGTERM'):
			try:
				signal.signal(getattr(signal, sig), self.stop if startup else signal.SIG_DFL)

			# some signals don't exist in windows, so skip them
			except AttributeError:
				pass


	def stop(self, *_: Any) -> None:
		self['running'] = False


	async def handle_run(self) -> None:
		self['running'] = True

		self.set_signal_handler(True)

		self['client'].open()
		self['database'].connect()
		self['cache'].setup()
		self['cleanup_thread'] = CacheCleanupThread(self)
		self['cleanup_thread'].start()
		self['workers'].start()

		runner = web.AppRunner(self, access_log_format='%{X-Forwarded-For}i "%r" %s %b "%{User-Agent}i"')
		await runner.setup()

		site = web.TCPSite(
			runner,
			host = self.config.listen,
			port = self.config.port,
			reuse_address = True
		)

		await site.start()
		self['starttime'] = datetime.now()

		while self['running']:
			await asyncio.sleep(0.25)

		await site.stop()

		self['workers'].stop()

		self.set_signal_handler(False)

		self['starttime'] = None
		self['running'] = False
		self['cleanup_thread'].stop()
		self['database'].disconnect()
		self['cache'].close()


class CachedStaticResource(StaticResource):
	def __init__(self, prefix: str, path: Path):
		StaticResource.__init__(self, prefix, path)

		self.cache: dict[str, bytes] = {}

		for filename in path.rglob('*'):
			if filename.is_dir():
				continue

			rel_path = str(filename.relative_to(path))

			with filename.open('rb') as fd:
				logging.debug('Loading static resource "%s"', rel_path)
				self.cache[rel_path] = fd.read()


	async def _handle(self, request: web.Request) -> web.StreamResponse:
		rel_url = request.match_info['filename']

		if Path(rel_url).anchor:
			raise web.HTTPForbidden()

		try:
			return web.Response(
				body = self.cache[rel_url],
				content_type = guess_type(rel_url)[0]
			)

		except KeyError:
			raise web.HTTPNotFound()


class CacheCleanupThread(Thread):
	def __init__(self, app: Application):
		Thread.__init__(self)

		self.app = app
		self.running = Event()


	def run(self) -> None:
		while self.running.is_set():
			time.sleep(3600)
			logging.verbose("Removing old cache items")
			self.app.cache.delete_old(14)


	def start(self) -> None:
		self.running.set()
		Thread.start(self)


	def stop(self) -> None:
		self.running.clear()


def format_error(request: web.Request, error: HttpError) -> Response:
	app: Application = request.app # type: ignore[assignment]

	if request.path.startswith(JSON_PATHS) or 'json' in request.headers.get('accept', ''):
		return Response.new({'error': error.message}, error.status, ctype = 'json')

	else:
		body = app.template.render('page/error.haml', request, e = error)
		return Response.new(body, error.status, ctype = 'html')


@web.middleware
async def handle_response_headers(
								request: web.Request,
								handler: Callable[[web.Request], Awaitable[Response]]) -> Response:

	request['hash'] = b64encode(get_random_bytes(16)).decode('ascii')
	request['token'] = None
	request['user'] = None

	app: Application = request.app # type: ignore[assignment]

	if request.path == "/" or request.path.startswith(TOKEN_PATHS):
		with app.database.session() as conn:
			tokens = (
				request.headers.get('Authorization', '').replace('Bearer', '').strip(),
				request.cookies.get('user-token')
			)

			for token in tokens:
				if not token:
					continue

				request['token'] = conn.get_app_by_token(token)

				if request['token'] is not None:
					request['user'] = conn.get_user(request['token'].user)

				break

	try:
		resp = await handler(request)

	except HttpError as e:
		resp = format_error(request, e)

	except HTTPException as e:
		if e.status == 404:
			try:
				text = (e.text or "").split(":")[1].strip()

			except IndexError:
				text = e.text or ""

			resp = format_error(request, HttpError(e.status, text))

		else:
			raise

	except Exception:
		resp = format_error(request, HttpError(500, 'Internal server error'))
		traceback.print_exc()

	resp.headers['Server'] = 'ActivityRelay'

	# Still have to figure out how csp headers work
	if resp.content_type == 'text/html' and not request.path.startswith("/api"):
		resp.headers['Content-Security-Policy'] = get_csp(request)

	if not request.app['dev'] and request.path.endswith(('.css', '.js', '.woff2')):
		# cache for 2 weeks
		resp.headers['Cache-Control'] = 'public,max-age=1209600,immutable'

	else:
		resp.headers['Cache-Control'] = 'no-store'

	return resp


async def handle_cleanup(app: Application) -> None:
	await app.client.close()
	app.cache.close()
	app.database.disconnect()
