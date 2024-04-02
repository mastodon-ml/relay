from __future__ import annotations

import asyncio
import multiprocessing
import signal
import time
import traceback
import typing

from aiohttp import web
from aiohttp.web import StaticResource
from aiohttp_swagger import setup_swagger
from aputils.signer import Signer
from datetime import datetime, timedelta
from mimetypes import guess_type
from pathlib import Path
from queue import Empty
from threading import Event, Thread

from . import logger as logging
from .cache import get_cache
from .config import Config
from .database import get_database
from .http_client import HttpClient
from .misc import IS_WINDOWS, check_open_port, get_resource
from .template import Template
from .views import VIEWS
from .views.api import handle_api_path
from .views.frontend import handle_frontend_path

if typing.TYPE_CHECKING:
	from collections.abc import Callable
	from bsql import Database, Row
	from .cache import Cache
	from .misc import Message, Response


def get_csp(request: web.Request) -> str:
	data = [
		"default-src 'none'",
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
				handle_api_path,
				handle_frontend_path,
				handle_response_headers
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
		self['workers'] = []

		self.cache.setup()
		self.on_cleanup.append(handle_cleanup) # type: ignore

		for path, view in VIEWS:
			self.router.add_view(path, view)

		setup_swagger(
			self,
			ui_version = 3,
			swagger_from_file = get_resource('data/swagger.yaml')
		)


	@property
	def cache(self) -> Cache:
		return self['cache']


	@property
	def client(self) -> HttpClient:
		return self['client']


	@property
	def config(self) -> Config:
		return self['config']


	@property
	def database(self) -> Database:
		return self['database']


	@property
	def signer(self) -> Signer:
		return self['signer']


	@signer.setter
	def signer(self, value: Signer | str) -> None:
		if isinstance(value, Signer):
			self['signer'] = value
			return

		self['signer'] = Signer(value, self.config.keyid)


	@property
	def template(self) -> Template:
		return self['template']


	@property
	def uptime(self) -> timedelta:
		if not self['start_time']:
			return timedelta(seconds=0)

		uptime = datetime.now() - self['start_time']

		return timedelta(seconds=uptime.seconds)


	def push_message(self, inbox: str, message: Message | bytes, instance: Row) -> None:
		self['push_queue'].put((inbox, message, instance))


	def register_static_routes(self) -> None:
		if self['dev']:
			static = StaticResource('/static', get_resource('frontend/static'))

		else:
			static = CachedStaticResource('/static', get_resource('frontend/static'))

		self.router.register_resource(static)


	def run(self) -> None:
		if self["running"]:
			return

		domain = self.config.domain
		host = self.config.listen
		port = self.config.port

		if not check_open_port(host, port):
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


	def stop(self, *_):
		self['running'] = False


	async def handle_run(self):
		self['running'] = True

		self.set_signal_handler(True)

		self['client'].open()
		self['database'].connect()
		self['cache'].setup()
		self['cleanup_thread'] = CacheCleanupThread(self)
		self['cleanup_thread'].start()

		for _ in range(self.config.workers):
			worker = PushWorker(self['push_queue'])
			worker.start()

			self['workers'].append(worker)

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

		for worker in self['workers']:
			worker.stop()

		self.set_signal_handler(False)

		self['starttime'] = None
		self['running'] = False
		self['cleanup_thread'].stop()
		self['workers'].clear()
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


class PushWorker(multiprocessing.Process):
	def __init__(self, queue: multiprocessing.Queue):
		if Application.DEFAULT is None:
			raise RuntimeError('Application not setup yet')

		multiprocessing.Process.__init__(self)

		self.queue = queue
		self.shutdown = multiprocessing.Event()
		self.path = Application.DEFAULT.config.path


	def stop(self) -> None:
		self.shutdown.set()


	def run(self) -> None:
		asyncio.run(self.handle_queue())


	async def handle_queue(self) -> None:
		if IS_WINDOWS:
			app = Application(self.path)
			client = app.client

			client.open()
			app.database.connect()
			app.cache.setup()

		else:
			client = HttpClient()
			client.open()

		while not self.shutdown.is_set():
			try:
				inbox, message, instance = self.queue.get(block=True, timeout=0.1)
				asyncio.create_task(client.post(inbox, message, instance))

			except Empty:
				await asyncio.sleep(0)

			# make sure an exception doesn't bring down the worker
			except Exception:
				traceback.print_exc()

		if IS_WINDOWS:
			app.database.disconnect()
			app.cache.close()

		await client.close()


@web.middleware
async def handle_response_headers(request: web.Request, handler: Callable) -> Response:
	resp = await handler(request)
	resp.headers['Server'] = 'ActivityRelay'

	# Still have to figure out how csp headers work
	if resp.content_type == 'text/html' and not request.path.startswith("/api"):
		resp.headers['Content-Security-Policy'] = get_csp(request)

	if not request.app['dev'] and request.path.endswith(('.css', '.js')):
		# cache for 2 weeks
		resp.headers['Cache-Control'] = 'public,max-age=1209600,immutable'

	else:
		resp.headers['Cache-Control'] = 'no-store'

	return resp


async def handle_cleanup(app: Application) -> None:
	await app.client.close()
	app.cache.close()
	app.database.disconnect()
