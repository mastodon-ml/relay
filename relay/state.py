from __future__ import annotations

from aputils import Signer
from asyncio import Event, get_running_loop, sleep
from blib import File, Path, set_signal_handler
from bsql import Database
from datetime import datetime, timedelta
from mimetypes import guess_type
from typing import Any

from aiohttp.web import (
	Application,
	AppRunner,
	HTTPForbidden,
	HTTPNotFound,
	Request,
	StaticResource,
	StreamResponse,
	TCPSite
)

from . import logger as logging
from .cache import Cache, get_cache
from .config import Config
from .database import Connection, get_database
from .database.schema import Instance
from .http_client import HttpClient
from .misc import Message, Response
from .template import Template
from .workers import PushWorkers


STATE: State | None = None


class State:
	__slots__ = (
		"cache",
		"client",
		"config",
		"database",
		"signer",
		"template",
		"workers",
		"dev",
		"shutdown",
		"startup_time"
	)


	@staticmethod
	def default() -> State:
		global STATE

		if STATE is None:
			return State(File("./relay.yaml"), register_global = True)

		return STATE


	def __init__(self, path: File | str | None, register_global: bool = False) -> None:
		global STATE

		if register_global:
			if STATE is not None:
				raise ValueError("Global state already set")

			STATE = self

		self.config: Config = Config(path, load = True)
		self.database: Database[Connection] = get_database(self)
		self.client: HttpClient = HttpClient(self)
		self.cache: Cache = get_cache(self)
		self.template: Template = Template(self)
		self.workers: PushWorkers = PushWorkers(self)
		self.shutdown: Event = Event()
		self.shutdown.set()

		self.dev: bool = False
		self.startup_time: datetime | None = None
		self.signer: Signer | None = None

		self.cache.setup()

		with self.database.session(False) as conn:
			if (privkey := conn.get_config("private-key")):
				self.signer = Signer(privkey, self.config.keyid)


	@property
	def uptime(self) -> timedelta:
		if self.startup_time is None:
			return timedelta(seconds=0)

		uptime = datetime.now() - self.startup_time
		return timedelta(seconds = uptime.seconds)


	async def close(self) -> None:
		await self.client.close()
		self.cache.close()
		self.database.disconnect()
		self.workers.stop()


	def push_message(self, inbox: str, message: Message, instance: Instance) -> None:
		self.workers.push_message(inbox, message, instance)


	async def handle_start(self) -> None:
		if not self.shutdown.is_set():
			return

		from .views import ROUTES, middleware as mw

		logging.info(
			"Starting webserver at %s (%s:%d)",
			self.config.domain,
			self.config.listen,
			self.config.port
		)

		self.shutdown.clear()
		self.client.open()
		set_signal_handler(self.stop)

		app = Application(middlewares = [
			mw.handle_response_headers,
			mw.handle_frontend_path
		])

		for method, path, handler in ROUTES:
			app.router.add_route(method, path, handler)

			if self.dev:
				static = StaticResource("/static", File.from_resource("relay", "frontend/static"))

			else:
				static = CachedStaticResource("/static", File.from_resource("relay", "frontend/static"))

			app.router.register_resource(static)

		runner = AppRunner(
			app, access_log_format = "%{X-Forwarded-For}i \"%r\" %s %b \"%{User-Agent}i\""
		)

		await runner.setup()

		site = TCPSite(
			runner,
			host = self.config.listen,
			port = self.config.port,
			reuse_address = True
		)

		await site.start()
		self.workers.start()
		self.client.open()

		self.startup_time = datetime.now()
		loop = get_running_loop()
		counter = 0

		while not self.shutdown.is_set():
			if counter < 3600:
				await sleep(1)
				counter += 1
				continue

			logging.verbose("Removing old cache items")
			counter = 0
			await loop.run_in_executor(None, self.cache.delete_old, 14)

		set_signal_handler(None)
		self.startup_time = None
		await site.stop()
		await self.close()


	def stop(self, *_: Any) -> None:
		self.shutdown.set()


class CachedStaticResource(StaticResource):
	def __init__(self, prefix: str, path: File):
		StaticResource.__init__(self, prefix, path)

		self.cache: dict[str, bytes] = {}

		for filename in path.glob(recursive = True):
			if filename.isdir:
				continue

			rel_path = filename.relative_to(path)

			with filename.open("rb") as fd:
				logging.debug("Loading static resource \"%s\"", rel_path)
				self.cache[str(rel_path)] = fd.read()


	async def _handle(self, request: Request) -> StreamResponse:
		rel_url = str(Path(request.match_info["filename"], True))

		if rel_url.startswith("/"):
			if len(rel_url) < 2:
				raise HTTPForbidden()

			rel_url = rel_url[1:]

		try:
			return Response(
				body = self.cache[rel_url],
				content_type = guess_type(rel_url)[0]
			)

		except KeyError:
			raise HTTPNotFound()
