import asyncio
import traceback
import typing

from aiohttp.client_exceptions import ClientConnectionError, ClientSSLError
from asyncio.exceptions import TimeoutError as AsyncTimeoutError
from bsql import Row
from dataclasses import dataclass
from multiprocessing import Event, Process, Queue, Value
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from queue import Empty, Queue as QueueType
from urllib.parse import urlparse

from . import application, logger as logging
from .http_client import HttpClient
from .misc import IS_WINDOWS, Message, get_app

if typing.TYPE_CHECKING:
	from .multiprocessing.synchronize import Syncronized


@dataclass
class QueueItem:
	pass


@dataclass
class PostItem(QueueItem):
	inbox: str
	message: Message
	instance: Row | None

	@property
	def domain(self) -> str:
		return urlparse(self.inbox).netloc


class PushWorker(Process):
	client: HttpClient


	def __init__(self, queue: QueueType[QueueItem], log_level: "Syncronized[str]") -> None:
		Process.__init__(self)

		self.queue: QueueType[QueueItem] = queue
		self.shutdown: EventType = Event()
		self.path: Path = get_app().config.path
		self.log_level: "Syncronized[str]" = log_level
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

				if isinstance(item, PostItem):
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

		except AsyncTimeoutError:
			logging.error('Timeout when pushing to %s', item.domain)

		except ClientConnectionError as e:
			logging.error('Failed to connect to %s for message push: %s', item.domain, str(e))

		except ClientSSLError as e:
			logging.error('SSL error when pushing to %s: %s', item.domain, str(e))


class PushWorkers(list[PushWorker]):
	def __init__(self, count: int) -> None:
		self.queue: QueueType[QueueItem] = Queue() # type: ignore[assignment]
		self._log_level: "Syncronized[str]" = Value("i", logging.get_level())
		self._count: int = count


	def push_item(self, item: QueueItem) -> None:
		self.queue.put(item)


	def push_message(self, inbox: str, message: Message, instance: Row) -> None:
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
