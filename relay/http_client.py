import traceback

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ClientConnectionError, ClientSSLError
from asyncio.exceptions import TimeoutError as AsyncTimeoutError
from aputils import Nodeinfo, WellKnownNodeinfo
from datetime import datetime
from cachetools import LRUCache
from json.decoder import JSONDecodeError
from urllib.parse import urlparse

from . import __version__
from . import logger as logging
from .misc import (
	MIMETYPES,
	DotDict,
	Message
)


HEADERS = {
	'Accept': f'{MIMETYPES["activity"]}, {MIMETYPES["json"]};q=0.9',
	'User-Agent': f'ActivityRelay/{__version__}'
}


class Cache(LRUCache):
	def set_maxsize(self, value):
		self.__maxsize = int(value)


class HttpClient:
	def __init__(self, database, limit=100, timeout=10, cache_size=1024):
		self.database = database
		self.cache = Cache(cache_size)
		self.cfg = {'limit': limit, 'timeout': timeout}
		self._conn = None
		self._session = None


	async def __aenter__(self):
		await self.open()
		return self


	async def __aexit__(self, *_):
		await self.close()


	@property
	def limit(self):
		return self.cfg['limit']


	@property
	def timeout(self):
		return self.cfg['timeout']


	async def open(self):
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


	async def close(self):
		if not self._session:
			return

		await self._session.close()
		await self._conn.close()

		self._conn = None
		self._session = None


	async def get(self, url, sign_headers=False, loads=None, force=False):
		await self.open()

		try: url, _ = url.split('#', 1)
		except: pass

		if not force and url in self.cache:
			return self.cache[url]

		headers = {}

		if sign_headers:
			headers.update(self.database.signer.sign_headers('GET', url, algorithm='original'))

		try:
			logging.debug('Fetching resource: %s', url)

			async with self._session.get(url, headers=headers) as resp:
				## Not expecting a response with 202s, so just return
				if resp.status == 202:
					return

				elif resp.status != 200:
					logging.verbose('Received error when requesting %s: %i', url, resp.status)
					logging.debug(await resp.read())
					return

				if loads:
					message = await resp.json(loads=loads)

				elif resp.content_type == MIMETYPES['activity']:
					message = await resp.json(loads=Message.parse)

				elif resp.content_type == MIMETYPES['json']:
					message = await resp.json(loads=DotDict.parse)

				else:
					# todo: raise TypeError or something
					logging.verbose('Invalid Content-Type for "%s": %s', url, resp.content_type)
					return logging.debug('Response: %s', await resp.read())

				logging.debug('%s >> resp %s', url, message.to_json(4))

				self.cache[url] = message
				return message

		except JSONDecodeError:
			logging.verbose('Failed to parse JSON')

		except ClientSSLError:
			logging.verbose('SSL error when connecting to %s', urlparse(url).netloc)

		except (AsyncTimeoutError, ClientConnectionError):
			logging.verbose('Failed to connect to %s', urlparse(url).netloc)

		except Exception as e:
			traceback.print_exc()


	async def post(self, url, message):
		await self.open()

		instance = self.database.get_inbox(url)

		## Using the old algo by default is probably a better idea right now
		if instance and instance.get('software') in {'mastodon'}:
			algorithm = 'hs2019'

		else:
			algorithm = 'original'

		headers = {'Content-Type': 'application/activity+json'}
		headers.update(self.database.signer.sign_headers('POST', url, message, algorithm=algorithm))

		try:
			logging.verbose('Sending "%s" to %s', message.type, url)

			async with self._session.post(url, headers=headers, data=message.to_json()) as resp:
				## Not expecting a response, so just return
				if resp.status in {200, 202}:
					return logging.verbose('Successfully sent "%s" to %s', message.type, url)

				logging.verbose('Received error when pushing to %s: %i', url, resp.status)
				return logging.verbose(await resp.read()) # change this to debug

		except ClientSSLError:
			logging.warning('SSL error when pushing to %s', urlparse(url).netloc)

		except (AsyncTimeoutError, ClientConnectionError):
			logging.warning('Failed to connect to %s for message push', urlparse(url).netloc)

		## prevent workers from being brought down
		except Exception as e:
			traceback.print_exc()


	## Additional methods ##
	async def fetch_nodeinfo(self, domain):
		nodeinfo_url = None
		wk_nodeinfo = await self.get(
			f'https://{domain}/.well-known/nodeinfo',
			loads = WellKnownNodeinfo.parse
		)

		if not wk_nodeinfo:
			logging.verbose('Failed to fetch well-known nodeinfo url for %s', domain)
			return False

		for version in ['20', '21']:
			try:
				nodeinfo_url = wk_nodeinfo.get_url(version)

			except KeyError:
				pass

		if not nodeinfo_url:
			logging.verbose('Failed to fetch nodeinfo url for %s', domain)
			return False

		return await self.get(nodeinfo_url, loads=Nodeinfo.parse) or False


async def get(database, *args, **kwargs):
	async with HttpClient(database) as client:
		return await client.get(*args, **kwargs)


async def post(database, *args, **kwargs):
	async with HttpClient(database) as client:
		return await client.post(*args, **kwargs)


async def fetch_nodeinfo(database, *args, **kwargs):
	async with HttpClient(database) as client:
		return await client.fetch_nodeinfo(*args, **kwargs)
