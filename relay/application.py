from __future__ import annotations

import asyncio
import queue
import signal
import threading
import traceback
import typing

from aiohttp import web
from aputils.signer import Signer
from datetime import datetime, timedelta

from . import logger as logging
from .cache import get_cache
from .config import Config
from .database import get_database
from .http_client import HttpClient
from .misc import check_open_port
from .views import VIEWS

if typing.TYPE_CHECKING:
	from tinysql import Database, Row
	from typing import Any
	from .cache import Cache
	from .misc import Message


# pylint: disable=unsubscriptable-object

class Application(web.Application):
	DEFAULT: Application = None

	def __init__(self, cfgpath: str):
		web.Application.__init__(self)

		Application.DEFAULT = self

		self['signer'] = None
		self['config'] = Config(cfgpath, load = True)
		self['database'] = get_database(self.config)
		self['client'] = HttpClient()
		self['cache'] = get_cache(self)

		self['workers'] = []
		self['last_worker'] = 0
		self['start_time'] = None
		self['running'] = False

		for path, view in VIEWS:
			self.router.add_view(path, view)


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
	def uptime(self) -> timedelta:
		if not self['start_time']:
			return timedelta(seconds=0)

		uptime = datetime.now() - self['start_time']

		return timedelta(seconds=uptime.seconds)


	def push_message(self, inbox: str, message: Message, instance: Row) -> None:
		if self.config.workers <= 0:
			asyncio.ensure_future(self.client.post(inbox, message, instance))
			return

		worker = self['workers'][self['last_worker']]
		worker.queue.put((inbox, message, instance))

		self['last_worker'] += 1

		if self['last_worker'] >= len(self['workers']):
			self['last_worker'] = 0


	def set_signal_handler(self, startup: bool) -> None:
		for sig in ('SIGHUP', 'SIGINT', 'SIGQUIT', 'SIGTERM'):
			try:
				signal.signal(getattr(signal, sig), self.stop if startup else signal.SIG_DFL)

			# some signals don't exist in windows, so skip them
			except AttributeError:
				pass


	def run(self) -> None:
		if not check_open_port(self.config.listen, self.config.port):
			logging.error('A server is already running on port %i', self.config.port)
			return

		for view in VIEWS:
			self.router.add_view(*view)

		logging.info(
			'Starting webserver at %s (%s:%i)',
			self.config.domain,
			self.config.listen,
			self.config.port
		)

		asyncio.run(self.handle_run())


	def stop(self, *_: Any) -> None:
		self['running'] = False


	async def handle_run(self) -> None:
		self['running'] = True

		self.set_signal_handler(True)

		if self.config.workers > 0:
			for _ in range(self.config.workers):
				worker = PushWorker(self)
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
		self['start_time'] = datetime.now()

		while self['running']:
			await asyncio.sleep(0.25)

		await site.stop()
		await self.client.close()

		self['start_time'] = None
		self['running'] = False
		self['workers'].clear()


class PushWorker(threading.Thread):
	def __init__(self, app: Application):
		threading.Thread.__init__(self)
		self.app = app
		self.queue = queue.Queue()
		self.client = None


	def run(self) -> None:
		asyncio.run(self.handle_queue())


	async def handle_queue(self) -> None:
		self.client = HttpClient()

		while self.app['running']:
			try:
				inbox, message, instance = self.queue.get(block=True, timeout=0.25)
				self.queue.task_done()
				logging.verbose('New push from Thread-%i', threading.get_ident())
				await self.client.post(inbox, message, instance)

			except queue.Empty:
				pass

			## make sure an exception doesn't bring down the worker
			except Exception:
				traceback.print_exc()

		await self.client.close()
