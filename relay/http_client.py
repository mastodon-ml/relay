from __future__ import annotations

import json
import traceback
import typing

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientConnectionError, ClientSSLError
from asyncio.exceptions import TimeoutError as AsyncTimeoutError
from aputils import AlgorithmType, JsonBase, Nodeinfo, ObjectType, WellKnownNodeinfo
from json.decoder import JSONDecodeError
from urllib.parse import urlparse

from . import __version__
from . import logger as logging
from .misc import MIMETYPES, Message, get_app

if typing.TYPE_CHECKING:
	from aputils import Signer
	from bsql import Row
	from typing import Any
	from .application import Application
	from .cache import Cache


T = typing.TypeVar('T', bound = JsonBase)
HEADERS = {
	'Accept': f'{MIMETYPES["activity"]}, {MIMETYPES["json"]};q=0.9',
	'User-Agent': f'ActivityRelay/{__version__}'
}


class HttpClient:
	def __init__(self, limit: int = 100, timeout: int = 10):
		self.limit = limit
		self.timeout = timeout
		self._conn: TCPConnector | None = None
		self._session: ClientSession | None = None


	async def __aenter__(self) -> HttpClient:
		self.open()
		return self


	async def __aexit__(self, *_: Any) -> None:
		await self.close()


	@property
	def app(self) -> Application:
		return get_app()


	@property
	def cache(self) -> Cache:
		return self.app.cache


	@property
	def signer(self) -> Signer:
		return self.app.signer


	def open(self) -> None:
		if self._session:
			return

		self._conn = TCPConnector(
			limit = self.limit,
			ttl_dns_cache = 300,
		)

		self._session = ClientSession(
			connector = self._conn,
			headers = HEADERS,
			connector_owner = True,
			timeout = ClientTimeout(total=self.timeout)
		)


	async def close(self) -> None:
		if self._session:
			await self._session.close()

		if self._conn:
			await self._conn.close()

		self._conn = None
		self._session = None


	async def _get(self, url: str, sign_headers: bool, force: bool) -> dict[str, Any] | None:
		if not self._session:
			raise RuntimeError('Client not open')

		try:
			url, _ = url.split('#', 1)

		except ValueError:
			pass

		if not force:
			try:
				if not (item := self.cache.get('request', url)).older_than(48):
					return json.loads(item.value)

			except KeyError:
				logging.verbose('No cached data for url: %s', url)

		headers = {}

		if sign_headers:
			headers = self.signer.sign_headers('GET', url, algorithm = AlgorithmType.HS2019)

		try:
			logging.debug('Fetching resource: %s', url)

			async with self._session.get(url, headers = headers) as resp:
				# Not expecting a response with 202s, so just return
				if resp.status == 202:
					return None

				data = await resp.text()

			if resp.status != 200:
				logging.verbose('Received error when requesting %s: %i', url, resp.status)
				logging.debug(data)
				return None

			self.cache.set('request', url, data, 'str')
			logging.debug('%s >> resp %s', url, json.dumps(json.loads(data), indent = 4))

			return json.loads(data)

		except JSONDecodeError:
			logging.verbose('Failed to parse JSON')
			return None

		except ClientSSLError as e:
			logging.verbose('SSL error when connecting to %s', urlparse(url).netloc)
			logging.warning(str(e))

		except (AsyncTimeoutError, ClientConnectionError) as e:
			logging.verbose('Failed to connect to %s', urlparse(url).netloc)
			logging.warning(str(e))

		except Exception:
			traceback.print_exc()

		return None


	async def get(self,
				url: str,
				sign_headers: bool,
				cls: type[T],
				force: bool = False) -> T | None:

		if not issubclass(cls, JsonBase):
			raise TypeError('cls must be a sub-class of "aputils.JsonBase"')

		if (data := (await self._get(url, sign_headers, force))) is None:
			return None

		return cls.parse(data)


	async def post(self, url: str, data: Message | bytes, instance: Row | None = None) -> None:
		if not self._session:
			raise RuntimeError('Client not open')

		# akkoma and pleroma do not support HS2019 and other software still needs to be tested
		if instance and instance['software'] in {'mastodon'}:
			algorithm = AlgorithmType.HS2019

		else:
			algorithm = AlgorithmType.RSASHA256

		body: bytes
		message: Message

		if isinstance(data, bytes):
			body = data
			message = Message.parse(data)

		else:
			body = data.to_json().encode("utf-8")
			message = data

		mtype = message.type.value if isinstance(message.type, ObjectType) else message.type
		headers = self.signer.sign_headers(
			'POST',
			url,
			body,
			headers = {'Content-Type': 'application/activity+json'},
			algorithm = algorithm
		)

		try:
			logging.verbose('Sending "%s" to %s', mtype, url)

			async with self._session.post(url, headers = headers, data = body) as resp:
				# Not expecting a response, so just return
				if resp.status in {200, 202}:
					logging.verbose('Successfully sent "%s" to %s', mtype, url)
					return

				logging.verbose('Received error when pushing to %s: %i', url, resp.status)
				logging.debug(await resp.read())
				logging.debug("message: %s", body.decode("utf-8"))
				logging.debug("headers: %s", json.dumps(headers, indent = 4))
				return

		except ClientSSLError as e:
			logging.warning('SSL error when pushing to %s', urlparse(url).netloc)
			logging.warning(str(e))

		except (AsyncTimeoutError, ClientConnectionError) as e:
			logging.warning('Failed to connect to %s for message push', urlparse(url).netloc)
			logging.warning(str(e))

		# prevent workers from being brought down
		except Exception:
			traceback.print_exc()


	async def fetch_nodeinfo(self, domain: str) -> Nodeinfo | None:
		nodeinfo_url = None
		wk_nodeinfo = await self.get(
			f'https://{domain}/.well-known/nodeinfo',
			False,
			WellKnownNodeinfo
		)

		if wk_nodeinfo is None:
			logging.verbose('Failed to fetch well-known nodeinfo url for %s', domain)
			return None

		for version in ('20', '21'):
			try:
				nodeinfo_url = wk_nodeinfo.get_url(version)

			except KeyError:
				pass

		if nodeinfo_url is None:
			logging.verbose('Failed to fetch nodeinfo url for %s', domain)
			return None

		return await self.get(nodeinfo_url, False, Nodeinfo)


async def get(*args: Any, **kwargs: Any) -> Any:
	async with HttpClient() as client:
		return await client.get(*args, **kwargs)


async def post(*args: Any, **kwargs: Any) -> None:
	async with HttpClient() as client:
		return await client.post(*args, **kwargs)


async def fetch_nodeinfo(*args: Any, **kwargs: Any) -> Nodeinfo | None:
	async with HttpClient() as client:
		return await client.fetch_nodeinfo(*args, **kwargs)
