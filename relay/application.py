from __future__ import annotations

import asyncio
import multiprocessing
import os
import signal
import subprocess
import sys
import time
import traceback
import typing

from aiohttp import web
from aiohttp_swagger import setup_swagger
from aputils.signer import Signer
from datetime import datetime, timedelta
from queue import Empty
from threading import Event, Thread

from . import logger as logging
from .cache import get_cache
from .config import Config
from .database import get_database
from .http_client import HttpClient
from .misc import check_open_port
from .views import VIEWS
from .views.api import handle_api_path

try:
	from importlib.resources import files as pkgfiles

except ImportError:
	from importlib_resources import files as pkgfiles

if typing.TYPE_CHECKING:
	from tinysql import Database, Row
	from .cache import Cache
	from .misc import Message


# pylint: disable=unsubscriptable-object

class Application(web.Application):
	DEFAULT: Application = None

	def __init__(self, cfgpath: str):
		web.Application.__init__(self,
			middlewares = [
				handle_api_path
			]
		)

		Application.DEFAULT = self

		self['running'] = None
		self['signer'] = None
		self['start_time'] = None
		self['cleanup_thread'] = None

		self['config'] = Config(cfgpath, load = True)
		self['database'] = get_database(self.config)
		self['client'] = HttpClient()
		self['cache'] = get_cache(self)
		self['cache'].setup()
		self['push_queue'] = multiprocessing.Queue()
		self['workers'] = []

		self.cache.setup()

		self.on_response_prepare.append(handle_access_log)
		self.on_cleanup.append(handle_cleanup)

		for path, view in VIEWS:
			self.router.add_view(path, view)

		setup_swagger(self,
			ui_version = 3,
			swagger_from_file = pkgfiles('relay').joinpath('data', 'swagger.yaml')
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
	def uptime(self) -> timedelta:
		if not self['start_time']:
			return timedelta(seconds=0)

		uptime = datetime.now() - self['start_time']

		return timedelta(seconds=uptime.seconds)


	def push_message(self, inbox: str, message: Message, instance: Row) -> None:
		self['push_queue'].put((inbox, message, instance))


	def run(self) -> None:
		if self["running"]:
			return

		if not check_open_port(self.config.listen, self.config.port):
			return logging.error(f'A server is already running on port {self.config.port}')

		logging.info(f'Starting webserver at {self.config.domain} ({self.config.listen}:{self.config.port})')
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

		self['database'].connect()
		self['cache'].setup()
		self['cleanup_thread'] = CacheCleanupThread(self)
		self['cleanup_thread'].start()

		for i in range(self.config.workers):
			worker = PushWorker(self['push_queue'])
			worker.start()

			self['workers'].append(worker)

		runner = web.AppRunner(self, access_log_format='%{X-Forwarded-For}i "%r" %s %b "%{User-Agent}i"')
		await runner.setup()

		site = web.TCPSite(runner,
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
		multiprocessing.Process.__init__(self)
		self.queue = queue
		self.shutdown = multiprocessing.Event()


	def stop(self) -> None:
		self.shutdown.set()


	def run(self) -> None:
		asyncio.run(self.handle_queue())


	async def handle_queue(self) -> None:
		client = HttpClient()

		while not self.shutdown.is_set():
			try:
				inbox, message, instance = self.queue.get(block=True, timeout=0.25)
				await client.post(inbox, message, instance)

			except Empty:
				pass

			## make sure an exception doesn't bring down the worker
			except Exception:
				traceback.print_exc()

		await client.close()



async def handle_access_log(request: web.Request, response: web.Response) -> None:
	address = request.headers.get(
		'X-Forwarded-For',
		request.headers.get(
			'X-Real-Ip',
			request.remote
		)
	)

	logging.info(
		'%s "%s %s" %i %i "%s"',
		address,
		request.method,
		request.path,
		response.status,
		response.content_length or 0,
		request.headers.get('User-Agent', 'n/a')
	)


async def handle_cleanup(app: Application) -> None:
	await app.client.close()
	app.cache.close()
	app.database.disconnect()
