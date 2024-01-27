from __future__ import annotations

import traceback
import typing

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientConnectionError, ClientSSLError
from asyncio.exceptions import TimeoutError as AsyncTimeoutError
from aputils.objects import Nodeinfo, WellKnownNodeinfo
from cachetools import LRUCache
from json.decoder import JSONDecodeError
from urllib.parse import urlparse

from . import __version__
from . import logger as logging
from .misc import MIMETYPES, Message, get_app

if typing.TYPE_CHECKING:
	from typing import Any


HEADERS = {
	'Accept': f'{MIMETYPES["activity"]}, {MIMETYPES["json"]};q=0.9',
	'User-Agent': f'ActivityRelay/{__version__}'
}


class HttpClient:
	def __init__(self, limit: int = 100, timeout: int = 10, cache_size: int = 1024):
		self.cache = LRUCache(cache_size)
		self.limit = limit
		self.timeout = timeout
		self._conn = None
		self._session = None


	async def __aenter__(self) -> HttpClient:
		await self.open()
		return self


	async def __aexit__(self, *_: Any) -> None:
		await self.close()


	async def open(self) -> None:
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
		if not self._session:
			return

		await self._session.close()
		await self._conn.close()

		self._conn = None
		self._session = None


	async def get(self,  # pylint: disable=too-many-branches
				url: str,
				sign_headers: bool = False,
				loads: callable | None = None,
				force: bool = False) -> Message | dict | None:

		await self.open()

		try:
			url, _ = url.split('#', 1)

		except ValueError:
			pass

		if not force and url in self.cache:
			return self.cache[url]

		headers = {}

		if sign_headers:
			get_app().signer.sign_headers('GET', url, algorithm = 'original')

		try:
			logging.debug('Fetching resource: %s', url)

			async with self._session.get(url, headers=headers) as resp:
				## Not expecting a response with 202s, so just return
				if resp.status == 202:
					return None

				if resp.status != 200:
					logging.verbose('Received error when requesting %s: %i', url, resp.status)
					logging.debug(await resp.read())
					return None

				if loads:
					message = await resp.json(loads=loads)

				elif resp.content_type == MIMETYPES['activity']:
					message = await resp.json(loads = Message.parse)

				elif resp.content_type == MIMETYPES['json']:
					message = await resp.json()

				else:
					logging.verbose('Invalid Content-Type for "%s": %s', url, resp.content_type)
					logging.debug('Response: %s', await resp.read())
					return None

				logging.debug('%s >> resp %s', url, message.to_json(4))

				self.cache[url] = message
				return message

		except JSONDecodeError:
			logging.verbose('Failed to parse JSON')

		except ClientSSLError:
			logging.verbose('SSL error when connecting to %s', urlparse(url).netloc)

		except (AsyncTimeoutError, ClientConnectionError):
			logging.verbose('Failed to connect to %s', urlparse(url).netloc)

		except Exception:
			traceback.print_exc()

		return None


	async def post(self, url: str, message: Message) -> None:
		await self.open()

		# todo: cache inboxes to avoid opening a db connection
		with get_app().database.connection() as conn:
			instance = conn.get_inbox(url)

		## Using the old algo by default is probably a better idea right now
		# pylint: disable=consider-ternary-expression
		if instance and instance['software'] in {'mastodon'}:
			algorithm = 'hs2019'

		else:
			algorithm = 'original'
		# pylint: enable=consider-ternary-expression

		headers = {'Content-Type': 'application/activity+json'}
		headers.update(get_app().signer.sign_headers('POST', url, message, algorithm=algorithm))

		try:
			logging.verbose('Sending "%s" to %s', message.type, url)

			async with self._session.post(url, headers=headers, data=message.to_json()) as resp:
				# Not expecting a response, so just return
				if resp.status in {200, 202}:
					logging.verbose('Successfully sent "%s" to %s', message.type, url)
					return

				logging.verbose('Received error when pushing to %s: %i', url, resp.status)
				logging.debug(await resp.read())
				return

		except ClientSSLError:
			logging.warning('SSL error when pushing to %s', urlparse(url).netloc)

		except (AsyncTimeoutError, ClientConnectionError):
			logging.warning('Failed to connect to %s for message push', urlparse(url).netloc)

		# prevent workers from being brought down
		except Exception:
			traceback.print_exc()


	async def fetch_nodeinfo(self, domain: str) -> Nodeinfo | None:
		nodeinfo_url = None
		wk_nodeinfo = await self.get(
			f'https://{domain}/.well-known/nodeinfo',
			loads = WellKnownNodeinfo.parse
		)

		if not wk_nodeinfo:
			logging.verbose('Failed to fetch well-known nodeinfo url for %s', domain)
			return None

		for version in ('20', '21'):
			try:
				nodeinfo_url = wk_nodeinfo.get_url(version)

			except KeyError:
				pass

		if not nodeinfo_url:
			logging.verbose('Failed to fetch nodeinfo url for %s', domain)
			return None

		return await self.get(nodeinfo_url, loads = Nodeinfo.parse) or None


async def get(*args: Any, **kwargs: Any) -> Message | dict | None:
	async with HttpClient() as client:
		return await client.get(*args, **kwargs)


async def post(*args: Any, **kwargs: Any) -> None:
	async with HttpClient() as client:
		return await client.post(*args, **kwargs)


async def fetch_nodeinfo(*args: Any, **kwargs: Any) -> Nodeinfo | None:
	async with HttpClient() as client:
		return await client.fetch_nodeinfo(*args, **kwargs)
