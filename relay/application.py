from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
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
from .views.api import handle_api_path

if typing.TYPE_CHECKING:
	from tinysql import Database, Row
	from .cache import Cache
	from .misc import Message


# pylint: disable=unsubscriptable-object

class Application(web.Application):
	DEFAULT: Application = None

	def __init__(self, cfgpath: str, gunicorn: bool = False):
		web.Application.__init__(self,
			middlewares = [
				handle_api_path
			]
		)

		Application.DEFAULT = self

		self['proc'] = None
		self['signer'] = None
		self['start_time'] = None

		self['config'] = Config(cfgpath, load = True)
		self['database'] = get_database(self.config)
		self['client'] = HttpClient()
		self['cache'] = get_cache(self)

		if not gunicorn:
			return

		self.on_response_prepare.append(handle_access_log)
		self.on_cleanup.append(handle_cleanup)

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
		asyncio.ensure_future(self.client.post(inbox, message, instance))


	def run(self, dev: bool = False) -> None:
		self.start(dev)

		while self['proc'] and self['proc'].poll() is None:
			time.sleep(0.1)

		self.stop()


	def set_signal_handler(self, startup: bool) -> None:
		for sig in ('SIGHUP', 'SIGINT', 'SIGQUIT', 'SIGTERM'):
			try:
				signal.signal(getattr(signal, sig), self.stop if startup else signal.SIG_DFL)

			# some signals don't exist in windows, so skip them
			except AttributeError:
				pass



	def start(self, dev: bool = False) -> None:
		if self['proc']:
			return

		if not check_open_port(self.config.listen, self.config.port):
			logging.error('Server already running on %s:%s', self.config.listen, self.config.port)
			return

		cmd = [
			sys.executable, '-m', 'gunicorn',
			'relay.application:main_gunicorn',
			'--bind', f'{self.config.listen}:{self.config.port}',
			'--worker-class', 'aiohttp.GunicornWebWorker',
			'--workers', str(self.config.workers),
			'--env', f'CONFIG_FILE={self.config.path}'
		]

		if dev:
			cmd.append('--reload')

		self.set_signal_handler(True)
		self['proc'] = subprocess.Popen(cmd)  # pylint: disable=consider-using-with


	def stop(self, *_) -> None:
		if not self['proc']:
			return

		self['proc'].terminate()
		time_wait = 0.0

		while self['proc'].poll() is None:
			time.sleep(0.1)
			time_wait += 0.1

			if time_wait >= 5.0:
				self['proc'].kill()
				break

		self.set_signal_handler(False)
		self['proc'] = None

		self.cache.close()
		self.database.close()


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
		len(response.body),
		request.headers.get('User-Agent', 'n/a')
	)


async def handle_cleanup(app: Application) -> None:
	await app.client.close()
	app.cache.close()
	app.database.close()


async def main_gunicorn():
	try:
		app = Application(os.environ['CONFIG_FILE'], gunicorn = True)

	except KeyError:
		logging.error('Failed to set "CONFIG_FILE" environment. Trying to run without gunicorn?')
		raise RuntimeError from None

	return app
