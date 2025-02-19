from __future__ import annotations

import docstring_parser
import inspect

from aiohttp.web import Request, StreamResponse
from blib import HttpError, HttpMethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from json.decoder import JSONDecodeError
from types import GenericAlias, UnionType
from typing import TYPE_CHECKING, Any, cast, get_origin, get_type_hints, overload

from .. import logger as logging
from ..api_objects import ApiObject
from ..misc import Response, get_state
from ..state import State

if TYPE_CHECKING:
	try:
		from typing import Self

	except ImportError:
		from typing_extensions import Self

	ApiRouteHandler = Callable[..., Awaitable[ApiObject | list[Any] | StreamResponse]]
	RouteHandler = Callable[[State, Request], Awaitable[Response]]
	HandlerCallback = Callable[[Request], Awaitable[Response]]


METHODS: dict[str, Method] = {}
ROUTES: list[tuple[str, str, HandlerCallback]] = []

DEFAULT_REDIRECT: str = "urn:ietf:wg:oauth:2.0:oob"
ALLOWED_HEADERS: set[str] = {
	"accept",
	"authorization",
	"content-type"
}


def parse_docstring(docstring: str) -> tuple[str, dict[str, str]]:
	params = {}
	ds = docstring_parser.parse(docstring)

	for param in ds.params:
		params[param.arg_name] = param.description or "n/a"

	if not ds.short_description and not ds.long_description:
		body = "n/a"

	elif ds.long_description is None:
		body = cast(str, ds.short_description)

	else:
		body = "\n\n".join([ds.short_description, ds.long_description]) # type: ignore[list-item]

	return body, params


def register_route(
				method: HttpMethod | str, *paths: str) -> Callable[[RouteHandler], HandlerCallback]:

	def wrapper(handler: RouteHandler) -> HandlerCallback:
		async def inner(request: Request) -> Response:
			return await handler(get_state(), request, **request.match_info)

		for path in paths:
			ROUTES.append((HttpMethod.parse(method), path, inner))

		return inner
	return wrapper


@dataclass(slots = True, frozen = True)
class Method:
	name: str
	category: str
	docs: str | None
	method: HttpMethod
	path: str
	return_type: type[Any]
	parameters: tuple[Parameter, ...]


	@classmethod
	def parse(
			cls: type[Self],
			func: ApiRouteHandler,
			method: HttpMethod,
			path: str,
			category: str) -> Self:

		annotations = get_type_hints(func)

		if (return_type := annotations.get("return")) is None:
			raise ValueError(f"Missing return type for {func.__name__}")

		if isinstance(return_type, GenericAlias):
			return_type = get_origin(return_type)

		if not issubclass(return_type, (Response, ApiObject, list)):
			raise ValueError(f"Invalid return type \"{return_type.__name__}\" for {func.__name__}")

		args = {key: value for key, value in inspect.signature(func).parameters.items()}
		docstring, paramdocs = parse_docstring(func.__doc__ or "")
		params = []

		if func.__doc__ is None:
			logging.warning(f"Missing docstring for \"{func.__name__}\"")

		for key, value in args.items():
			types: list[type[Any]] = []
			vtype = annotations[key]

			if isinstance(vtype, UnionType):
				for subtype in vtype.__args__:
					if subtype is type(None):
						continue

					types.append(subtype)

			elif vtype in {Request, State}:
				continue

			else:
				types.append(vtype)

			params.append(Parameter(
				key = key,
				docs = paramdocs.get(key, ""),
				default = value.default,
				types = tuple(types)
			))

			if not paramdocs.get(key):
				logging.warning(f"Missing docs for \"{key}\" parameter in \"{func.__name__}\"")

		rtype = annotations.get("return") or type(None)
		return cls(func.__name__, category, docstring, method, path, rtype, tuple(params))



@dataclass(slots = True, frozen = True)
class Parameter:
	key: str
	docs: str
	default: Any
	types: tuple[type[Any], ...]


	@property
	def has_default(self) -> bool:
		# why tf do you make me do this mypy!?
		return cast(bool, self.default != inspect.Parameter.empty)


	@property
	def key_str(self) -> str:
		if not self.has_default:
			return f"{self.key} *required"

		return self.key


	@property
	def type_str(self) -> str:
		return " | ".join(v.__name__ for v in self.types)


	def check_types(self, items: Sequence[type[Any]]) -> bool:
		for item in items:
			if isinstance(item, self.types):
				return True

		return False



class Route:
	handler: ApiRouteHandler
	docs: Method

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

		if (self.method, self.path) != (HttpMethod.POST, "/oauth/authorize"):
			if self.path != "/api/v1/user":
				METHODS[obj.__name__] = Method.parse(obj, self.method, self.path, self.category)

		self.handler = obj
		return self


	async def handle_request(self, request: Request) -> StreamResponse:
		request["application"] = None

		if request.method != "OPTIONS" and self.require_token:
			if (auth := request.headers.getone("Authorization", None)) is None:
				raise HttpError(401, "Missing token")

			try:
				authtype, code = auth.split(" ", 1)

			except IndexError:
				raise HttpError(401, "Invalid authorization heder format")

			if authtype != "Bearer":
				raise HttpError(401, f"Invalid authorization type: {authtype}")

			if not code:
				raise HttpError(401, "Missing token")

			with get_state().database.session(False) as s:
				if (application := s.get_app_by_token(code)) is None:
					raise HttpError(401, "Invalid token")

				if application.auth_code is not None:
					raise HttpError(401, "Invalid token")

			request["application"] = application

		if request.content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
			post_data = {key: value for key, value in (await request.post()).items()}

		elif request.content_type == "application/json":
			try:
				post_data = await request.json()

			except JSONDecodeError:
				raise HttpError(400, "Invalid JSON data")

		else:
			post_data = {key: str(value) for key, value in request.query.items()}

		try:
			response = await self.handler(get_state(), request, **post_data)

		except HttpError as error:
			return Response.new({"error": error.message}, error.status, ctype = "json")

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
