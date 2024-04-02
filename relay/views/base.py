from __future__ import annotations

import typing

from Crypto.Random import get_random_bytes
from aiohttp.abc import AbstractView
from aiohttp.hdrs import METH_ALL as METHODS
from aiohttp.web import HTTPMethodNotAllowed
from base64 import b64encode
from functools import cached_property
from json.decoder import JSONDecodeError

from ..misc import Response, get_app

if typing.TYPE_CHECKING:
	from aiohttp.web import Request
	from collections.abc import Callable, Generator, Sequence, Mapping
	from bsql import Database
	from typing import Any
	from ..application import Application
	from ..cache import Cache
	from ..config import Config
	from ..http_client import HttpClient
	from ..template import Template

	try:
		from typing import Self

	except ImportError:
		from typing_extensions import Self


VIEWS: list[tuple[str, type[View]]] = []


def convert_data(data: Mapping[str, Any]) -> dict[str, str]:
	return {key: str(value) for key, value in data.items()}


def register_route(*paths: str) -> Callable:
	def wrapper(view: type[View]) -> type[View]:
		for path in paths:
			VIEWS.append((path, view))

		return view
	return wrapper


class View(AbstractView):
	def __await__(self) -> Generator[Any, None, Response]:
		if self.request.method not in METHODS:
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods)

		if not (handler := self.handlers.get(self.request.method)):
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods)

		return self._run_handler(handler).__await__()


	@classmethod
	async def run(cls: type[Self], method: str, request: Request, **kwargs: Any) -> Response:
		view = cls(request)
		return await view.handlers[method](request, **kwargs)


	async def _run_handler(self, handler: Callable[..., Any], **kwargs: Any) -> Response:
		self.request['hash'] = b64encode(get_random_bytes(16)).decode('ascii')
		return await handler(self.request, **self.request.match_info, **kwargs)


	async def options(self, request: Request) -> Response:
		return Response.new()


	@cached_property
	def allowed_methods(self) -> Sequence[str]:
		return tuple(self.handlers.keys())


	@cached_property
	def handlers(self) -> dict[str, Callable[..., Any]]:
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
	def database(self) -> Database:
		return self.app.database


	@property
	def template(self) -> Template:
		return self.app['template']


	async def get_api_data(self,
							required: list[str],
							optional: list[str]) -> dict[str, str] | Response:

		if self.request.content_type in {'x-www-form-urlencoded', 'multipart/form-data'}:
			post_data = convert_data(await self.request.post())

		elif self.request.content_type == 'application/json':
			try:
				post_data = convert_data(await self.request.json())

			except JSONDecodeError:
				return Response.new_error(400, 'Invalid JSON data', 'json')

		else:
			post_data = convert_data(self.request.query)

		data = {}

		try:
			for key in required:
				data[key] = post_data[key]

		except KeyError as e:
			return Response.new_error(400, f'Missing {str(e)} pararmeter', 'json')

		for key in optional:
			data[key] = post_data.get(key, '')

		return data
