from __future__ import annotations

from aiohttp.web import Request, StreamResponse
from blib import HttpError, HttpMethod
from collections.abc import Awaitable, Callable, Mapping
from json.decoder import JSONDecodeError
from typing import TYPE_CHECKING, Any, overload

from ..api_objects import ApiObject
from ..misc import Response, get_app

if TYPE_CHECKING:
	from ..application import Application

	try:
		from typing import Self

	except ImportError:
		from typing_extensions import Self

	ApiRouteHandler = Callable[..., Awaitable[ApiObject | list[Any] | StreamResponse]]
	RouteHandler = Callable[[Application, Request], Awaitable[Response]]
	HandlerCallback = Callable[[Request], Awaitable[Response]]


ROUTES: list[tuple[str, str, HandlerCallback]] = []

DEFAULT_REDIRECT: str = 'urn:ietf:wg:oauth:2.0:oob'
ALLOWED_HEADERS: set[str] = {
	'accept',
	'authorization',
	'content-type'
}


def convert_data(data: Mapping[str, Any]) -> dict[str, str]:
	return {key: str(value) for key, value in data.items()}


def register_route(
				method: HttpMethod | str, *paths: str) -> Callable[[RouteHandler], HandlerCallback]:

	def wrapper(handler: RouteHandler) -> HandlerCallback:
		async def inner(request: Request) -> Response:
			return await handler(get_app(), request, **request.match_info)

		for path in paths:
			ROUTES.append((HttpMethod.parse(method), path, inner))

		return inner
	return wrapper


class Route:
	handler: ApiRouteHandler

	def __init__(self,
				method: HttpMethod,
				path: str,
				category: str,
				require_token: bool) -> None:

		self.method: HttpMethod = HttpMethod.parse(method)
		self.path: str = path
		self.category: str = category
		self.require_token: bool = require_token

		ROUTES.append((self.method, self.path, self)) # type: ignore[arg-type]


	@overload
	def __call__(self, obj: Request) -> Awaitable[StreamResponse]:
		...


	@overload
	def __call__(self, obj: ApiRouteHandler) -> Self:
		...


	def __call__(self, obj: Request | ApiRouteHandler) -> Self | Awaitable[StreamResponse]:
		if isinstance(obj, Request):
			return self.handle_request(obj)

		self.handler = obj
		return self


	async def handle_request(self, request: Request) -> StreamResponse:
		request["application"] = None

		if request.method != "OPTIONS" and self.require_token:
			if (auth := request.headers.getone("Authorization", None)) is None:
				raise HttpError(401, 'Missing token')

			try:
				authtype, code = auth.split(" ", 1)

			except IndexError:
				raise HttpError(401, "Invalid authorization heder format")

			if authtype != "Bearer":
				raise HttpError(401, f"Invalid authorization type: {authtype}")

			if not code:
				raise HttpError(401, "Missing token")

			with get_app().database.session(False) as s:
				if (application := s.get_app_by_token(code)) is None:
					raise HttpError(401, "Invalid token")

				if application.auth_code is not None:
					raise HttpError(401, "Invalid token")

			request["application"] = application

		if request.content_type in {'application/x-www-form-urlencoded', 'multipart/form-data'}:
			post_data = {key: value for key, value in (await request.post()).items()}

		elif request.content_type == 'application/json':
			try:
				post_data = await request.json()

			except JSONDecodeError:
				raise HttpError(400, 'Invalid JSON data')

		else:
			post_data = {key: str(value) for key, value in request.query.items()}

		try:
			response = await self.handler(get_app(), request, **post_data)

		except HttpError as error:
			return Response.new({'error': error.message}, error.status, ctype = "json")

		headers = {
			"Access-Control-Allow-Origin": "*",
			"Access-Control-Allow-Headers": ", ".join(ALLOWED_HEADERS)
		}

		if isinstance(response, StreamResponse):
			response.headers.update(headers)
			return response

		if isinstance(response, ApiObject):
			return Response.new(response.to_json(), headers = headers, ctype = "json")

		if isinstance(response, list):
			data = []

			for item in response:
				if isinstance(item, ApiObject):
					data.append(item.to_dict())

			response = data

		return Response.new(response, headers = headers, ctype = "json")
