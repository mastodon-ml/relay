import asyncio
import os
import queue
import signal
import threading
import traceback

from aiohttp import web
from datetime import datetime, timedelta

from . import logger as logging
from .config import RelayConfig
from .database import RelayDatabase
from .http_client import HttpClient
from .misc import DotDict, check_open_port, set_app
from .views import VIEWS


class Application(web.Application):
	def __init__(self, cfgpath):
		web.Application.__init__(self)

		self['starttime'] = None
		self['running'] = False
		self['config'] = RelayConfig(cfgpath)

		if not self['config'].load():
			self['config'].save()

		if self.config.is_docker:
			self.config.update({
				'db': '/data/relay.jsonld',
				'listen': '0.0.0.0',
				'port': 8080
			})

		self['workers'] = []
		self['last_worker'] = 0

		set_app(self)

		self['database'] = RelayDatabase(self['config'])
		self['database'].load()

		self['client'] = HttpClient(
			database = self.database,
			limit = self.config.push_limit,
			timeout = self.config.timeout,
			cache_size = self.config.json_cache
		)

		for path, view in VIEWS:
			self.router.add_view(path, view)


	@property
	def client(self):
		return self['client']


	@property
	def config(self):
		return self['config']


	@property
	def database(self):
		return self['database']


	@property
	def uptime(self):
		if not self['starttime']:
			return timedelta(seconds=0)

		uptime = datetime.now() - self['starttime']

		return timedelta(seconds=uptime.seconds)


	def push_message(self, inbox, message):
		if self.config.workers <= 0:
			return asyncio.ensure_future(self.client.post(inbox, message))

		worker = self['workers'][self['last_worker']]
		worker.queue.put((inbox, message))

		self['last_worker'] += 1

		if self['last_worker'] >= len(self['workers']):
			self['last_worker'] = 0


	def set_signal_handler(self, startup):
		for sig in {'SIGHUP', 'SIGINT', 'SIGQUIT', 'SIGTERM'}:
			try:
				signal.signal(getattr(signal, sig), self.stop if startup else signal.SIG_DFL)

			# some signals don't exist in windows, so skip them
			except AttributeError:
				pass


	def run(self):
		if not check_open_port(self.config.listen, self.config.port):
			return logging.error('A server is already running on port %i', self.config.port)

		for view in VIEWS:
			self.router.add_view(*view)

		logging.info(
			'Starting webserver at %s (%s:%i)',
			self.config.host,
			self.config.listen,
			self.config.port
		)

		asyncio.run(self.handle_run())


	def stop(self, *_):
		self['running'] = False


	async def handle_run(self):
		self['running'] = True

		self.set_signal_handler(True)

		if self.config.workers > 0:
			for i in range(self.config.workers):
				worker = PushWorker(self)
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
		await self.client.close()

		self['starttime'] = None
		self['running'] = False
		self['workers'].clear()


class PushWorker(threading.Thread):
	def __init__(self, app):
		threading.Thread.__init__(self)
		self.app = app
		self.queue = queue.Queue()


	def run(self):
		asyncio.run(self.handle_queue())


	async def handle_queue(self):
		self.client = HttpClient(
			database = self.app.database,
			limit = self.app.config.push_limit,
			timeout = self.app.config.timeout,
			cache_size = self.app.config.json_cache
		)

		while self.app['running']:
			try:
				inbox, message = self.queue.get(block=True, timeout=0.25)
				self.queue.task_done()
				logging.verbose('New push from Thread-%i', threading.get_ident())
				await self.client.post(inbox, message)

			except queue.Empty:
				pass

			## make sure an exception doesn't bring down the worker
			except Exception:
				traceback.print_exc()

		await self.client.close()
