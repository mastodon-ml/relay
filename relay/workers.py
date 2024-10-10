from __future__ import annotations

import asyncio
import traceback

from aiohttp.client_exceptions import ClientConnectionError, ClientSSLError
from asyncio.exceptions import TimeoutError as AsyncTimeoutError
from blib import HttpError
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue, Value
from multiprocessing.queues import Queue as QueueType
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from queue import Empty
from urllib.parse import urlparse

from . import application, logger as logging
from .database.schema import Instance
from .http_client import HttpClient
from .misc import IS_WINDOWS, Message, get_app


@dataclass
class PostItem:
	inbox: str
	message: Message
	instance: Instance | None

	@property
	def domain(self) -> str:
		return urlparse(self.inbox).netloc


class PushWorker(Process):
	client: HttpClient


	def __init__(self, queue: QueueType[PostItem], log_level: Synchronized[int]) -> None:
		Process.__init__(self)

		self.queue: QueueType[PostItem] = queue
		self.shutdown: EventType = Event()
		self.path: Path = get_app().config.path
		self.log_level: Synchronized[int] = log_level
		self._log_level_changed: EventType = Event()


	def stop(self) -> None:
		self.shutdown.set()


	def run(self) -> None:
		asyncio.run(self.handle_queue())


	async def handle_queue(self) -> None:
		if IS_WINDOWS:
			app = application.Application(self.path)
			self.client = app.client

			self.client.open()
			app.database.connect()
			app.cache.setup()

		else:
			self.client = HttpClient()
			self.client.open()

		logging.verbose("[%i] Starting worker", self.pid)

		while not self.shutdown.is_set():
			try:
				if self._log_level_changed.is_set():
					logging.set_level(logging.LogLevel.parse(self.log_level.value))
					self._log_level_changed.clear()

				item = self.queue.get(block=True, timeout=0.1)
				asyncio.create_task(self.handle_post(item))

			except Empty:
				await asyncio.sleep(0)

			except Exception:
				traceback.print_exc()

		if IS_WINDOWS:
			app.database.disconnect()
			app.cache.close()

		await self.client.close()


	async def handle_post(self, item: PostItem) -> None:
		try:
			await self.client.post(item.inbox, item.message, item.instance)

		except HttpError as e:
			logging.error('HTTP Error when pushing to %s: %i %s', item.inbox, e.status, e.message)

		except AsyncTimeoutError:
			logging.error('Timeout when pushing to %s', item.domain)

		except ClientConnectionError as e:
			logging.error('Failed to connect to %s for message push: %s', item.domain, str(e))

		except ClientSSLError as e:
			logging.error('SSL error when pushing to %s: %s', item.domain, str(e))


class PushWorkers(list[PushWorker]):
	def __init__(self, count: int) -> None:
		self.queue: QueueType[PostItem] = Queue()
		self._log_level: Synchronized[int] = Value("i", logging.get_level())
		self._count: int = count


	def push_message(self, inbox: str, message: Message, instance: Instance) -> None:
		self.queue.put(PostItem(inbox, message, instance))


	def set_log_level(self, value: logging.LogLevel) -> None:
		self._log_level.value = value

		for worker in self:
			worker._log_level_changed.set()


	def start(self) -> None:
		if len(self) > 0:
			return

		for _ in range(self._count):
			worker = PushWorker(self.queue, self._log_level)
			worker.start()
			self.append(worker)


	def stop(self) -> None:
		for worker in self:
			worker.stop()

		self.clear()
