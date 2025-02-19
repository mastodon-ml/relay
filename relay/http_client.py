from __future__ import annotations

import json

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aputils import AlgorithmType, Nodeinfo, ObjectType, WellKnownNodeinfo
from blib import HttpError, JsonBase
from typing import TYPE_CHECKING, Any, TypeVar, overload

from . import __version__, logger as logging
from .database.schema import Instance
from .misc import MIMETYPES, Message

if TYPE_CHECKING:
	from .state import State


T = TypeVar("T", bound = JsonBase[Any])

HEADERS = {
	"Accept": f"{MIMETYPES['activity']}, {MIMETYPES['json']};q=0.9",
	"User-Agent": f"ActivityRelay/{__version__}"
}

SUPPORTS_HS2019 = {
	'friendica',
	'gotosocial',
	'hubzilla'
	'mastodon',
	'socialhome',
	'misskey',
	'catodon',
	'cherrypick',
	'firefish',
	'foundkey',
	'iceshrimp',
	'sharkey'
}


class EmptyBodyError(Exception):
	pass


class HttpClient:
	def __init__(self, state: State, limit: int = 100, timeout: int = 10):
		self.state: State = state
		self.limit: int = limit
		self.timeout: int = timeout
		self._conn: TCPConnector | None = None
		self._session: ClientSession | None = None


	async def __aenter__(self) -> HttpClient:
		self.open()
		return self


	async def __aexit__(self, *_: Any) -> None:
		await self.close()


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


	async def _get(self,
					url: str,
					sign_headers: bool,
					force: bool,
					old_algo: bool) -> str | None:

		if not self._session:
			raise RuntimeError("Client not open")

		url = url.split("#", 1)[0]

		if not force:
			try:
				if not (item := self.state.cache.get("request", url)).older_than(48):
					return item.value # type: ignore [no-any-return]

			except KeyError:
				logging.verbose("No cached data for url: %s", url)

		headers = {}

		if sign_headers and self.state.signer is not None:
			algo = AlgorithmType.RSASHA256 if old_algo else AlgorithmType.HS2019
			headers = self.state.signer.sign_headers("GET", url, algorithm = algo)

		logging.debug("Fetching resource: %s", url)

		async with self._session.get(url, headers = headers) as resp:
			# Not expecting a response with 202s, so just return
			if resp.status == 202:
				return None

			data = await resp.text()

		if resp.status not in (200, 202):
			try:
				error = json.loads(data)["error"]

			except Exception:
				error = data

			raise HttpError(resp.status, error)

		self.state.cache.set("request", url, data, "str")
		return data


	@overload
	async def get(self,
				url: str,
				sign_headers: bool,
				cls: None = None,
				force: bool = False,
				old_algo: bool = True) -> str | None: ...


	@overload
	async def get(self,
				url: str,
				sign_headers: bool,
				cls: type[T] = JsonBase, # type: ignore[assignment]
				force: bool = False,
				old_algo: bool = True) -> T: ...


	async def get(self,
				url: str,
				sign_headers: bool,
				cls: type[T] | None = None,
				force: bool = False,
				old_algo: bool = True) -> T | str | None:

		if cls is not None and not issubclass(cls, JsonBase):
			raise TypeError("cls must be a sub-class of \"blib.JsonBase\"")

		data = await self._get(url, sign_headers, force, old_algo)

		if cls is not None:
			if data is None:
				# this shouldn't actually get raised, but keeping just in case
				raise EmptyBodyError(f"GET {url}")

			return cls.parse(data)

		return data


	async def post(self, url: str, data: Message | bytes, instance: Instance | None = None) -> None:
		if not self._session:
			raise RuntimeError("Client not open")

		if self.state.signer is None:
			raise RuntimeError("Signer is not available")

		# akkoma and pleroma do not support HS2019 and other software still needs to be tested
		if instance is not None and instance.software in SUPPORTS_HS2019:
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
		headers = self.state.signer.sign_headers(
			"POST",
			url,
			body,
			headers = {"Content-Type": "application/activity+json"},
			algorithm = algorithm
		)

		logging.verbose("Sending \"%s\" to %s", mtype, url)

		async with self._session.post(url, headers = headers, data = body) as resp:
			if resp.status not in (200, 202):
				raise HttpError(
					resp.status,
					await resp.text(),
					headers = {k: v for k, v in resp.headers.items()}
				)


	async def fetch_nodeinfo(self, domain: str, force: bool = False) -> Nodeinfo:
		nodeinfo_url = None
		wk_nodeinfo = await self.get(
			f"https://{domain}/.well-known/nodeinfo", False, WellKnownNodeinfo, force
		)

		for version in ("20", "21"):
			try:
				nodeinfo_url = wk_nodeinfo.get_url(version)

			except KeyError:
				pass

		if nodeinfo_url is None:
			raise ValueError(f"Failed to fetch nodeinfo url for {domain}")

		return await self.get(nodeinfo_url, False, Nodeinfo, force)
