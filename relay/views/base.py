from __future__ import annotations

from aiohttp.abc import AbstractView
from aiohttp.hdrs import METH_ALL as METHODS
from aiohttp.web import Request
from blib import HttpError
from bsql import Database
from collections.abc import Awaitable, Callable, Generator, Sequence, Mapping
from functools import cached_property
from json.decoder import JSONDecodeError
from typing import TYPE_CHECKING, Any

from ..cache import Cache
from ..config import Config
from ..database import Connection
from ..http_client import HttpClient
from ..misc import Response, get_app

if TYPE_CHECKING:
	from typing import Self
	from ..application import Application
	from ..template import Template


HandlerCallback = Callable[[Request], Awaitable[Response]]
VIEWS: list[tuple[str, type[View]]] = []


def convert_data(data: Mapping[str, Any]) -> dict[str, str]:
	return {key: str(value) for key, value in data.items()}


def register_route(*paths: str) -> Callable[[type[View]], type[View]]:
	def wrapper(view: type[View]) -> type[View]:
		for path in paths:
			VIEWS.append((path, view))

		return view
	return wrapper


class View(AbstractView):
	def __await__(self) -> Generator[Any, None, Response]:
		if self.request.method not in METHODS:
			raise HttpError(405, f'"{self.request.method}" method not allowed')

		if not (handler := self.handlers.get(self.request.method)):
			raise HttpError(405, f'"{self.request.method}" method not allowed')

		return self._run_handler(handler).__await__()


	@classmethod
	async def run(cls: type[Self], method: str, request: Request, **kwargs: Any) -> Response:
		view = cls(request)
		return await view.handlers[method](request, **kwargs)


	async def _run_handler(self, handler: HandlerCallback, **kwargs: Any) -> Response:
		return await handler(self.request, **self.request.match_info, **kwargs)


	async def options(self, request: Request) -> Response:
		return Response.new()


	@cached_property
	def allowed_methods(self) -> Sequence[str]:
		return tuple(self.handlers.keys())


	@cached_property
	def handlers(self) -> dict[str, HandlerCallback]:
		data = {}

		for method in METHODS:
			try:
				data[method] = getattr(self, method.lower())

			except AttributeError:
				continue

		return data


	@property
	def app(self) -> Application:
		return get_app()


	@property
	def cache(self) -> Cache:
		return self.app.cache


	@property
	def client(self) -> HttpClient:
		return self.app.client


	@property
	def config(self) -> Config:
		return self.app.config


	@property
	def database(self) -> Database[Connection]:
		return self.app.database


	@property
	def template(self) -> Template:
		return self.app['template'] # type: ignore[no-any-return]


	async def get_api_data(self,
							required: list[str],
							optional: list[str]) -> dict[str, str]:

		if self.request.content_type in {'application/x-www-form-urlencoded', 'multipart/form-data'}:
			post_data = convert_data(await self.request.post())
			# post_data = {key: value for key, value in parse_qsl(await self.request.text())}

		elif self.request.content_type == 'application/json':
			try:
				post_data = convert_data(await self.request.json())

			except JSONDecodeError:
				raise HttpError(400, 'Invalid JSON data')

		else:
			post_data = convert_data(self.request.query)

		data = {}

		try:
			for key in required:
				data[key] = post_data[key]

		except KeyError as e:
			raise HttpError(400, f'Missing {str(e)} pararmeter') from None

		for key in optional:
			data[key] = post_data.get(key) # type: ignore[assignment]

		return data
