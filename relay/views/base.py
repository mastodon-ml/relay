from __future__ import annotations

import typing

from aiohttp.abc import AbstractView
from aiohttp.hdrs import METH_ALL as METHODS
from aiohttp.web import HTTPMethodNotAllowed
from functools import cached_property
from json.decoder import JSONDecodeError

from ..misc import Response

if typing.TYPE_CHECKING:
	from collections.abc import Callable, Coroutine, Generator
	from bsql import Database
	from typing import Self
	from ..application import Application
	from ..cache import Cache
	from ..config import Config
	from ..http_client import HttpClient
	from ..template import Template


VIEWS = []


def register_route(*paths: str) -> Callable:
	def wrapper(view: View) -> View:
		for path in paths:
			VIEWS.append([path, view])

		return view
	return wrapper


class View(AbstractView):
	def __await__(self) -> Generator[Response]:
		if self.request.method not in METHODS:
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods)

		if not (handler := self.handlers.get(self.request.method)):
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods)

		return self._run_handler(handler).__await__()


	@classmethod
	async def run(cls: type[Self], method: str, request: Request, **kwargs: Any) -> Self:
		view = cls(request)
		return await view.handlers[method](request, **kwargs)


	async def _run_handler(self, handler: Coroutine, **kwargs: Any) -> Response:
		return await handler(self.request, **self.request.match_info, **kwargs)


	@cached_property
	def allowed_methods(self) -> tuple[str]:
		return tuple(self.handlers.keys())


	@cached_property
	def handlers(self) -> dict[str, Coroutine]:
		data = {}

		for method in METHODS:
			try:
				data[method] = getattr(self, method.lower())

			except AttributeError:
				continue

		return data


	# app components
	@property
	def app(self) -> Application:
		return self.request.app


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
			post_data = await self.request.post()

		elif self.request.content_type == 'application/json':
			try:
				post_data = await self.request.json()

			except JSONDecodeError:
				return Response.new_error(400, 'Invalid JSON data', 'json')

		else:
			post_data = self.request.query

		data = {}

		try:
			for key in required:
				data[key] = post_data[key]

		except KeyError as e:
			return Response.new_error(400, f'Missing {str(e)} pararmeter', 'json')

		for key in optional:
			data[key] = post_data.get(key)

		return data
