from __future__ import annotations

import json
import os
import socket
import typing

from aiohttp.abc import AbstractView
from aiohttp.hdrs import METH_ALL as METHODS
from aiohttp.web import Response as AiohttpResponse
from aiohttp.web_exceptions import HTTPMethodNotAllowed
from aputils.message import Message as ApMessage
from functools import cached_property
from uuid import uuid4

if typing.TYPE_CHECKING:
	from collections.abc import Coroutine, Generator
	from tinysql import Connection
	from typing import Any, Awaitable
	from .application import Application
	from .cache import Cache
	from .config import Config
	from .database import Database
	from .http_client import HttpClient


IS_DOCKER = bool(os.environ.get('DOCKER_RUNNING'))
MIMETYPES = {
	'activity': 'application/activity+json',
	'html': 'text/html',
	'json': 'application/json',
	'text': 'text/plain'
}

NODEINFO_NS = {
	'20': 'http://nodeinfo.diaspora.software/ns/schema/2.0',
	'21': 'http://nodeinfo.diaspora.software/ns/schema/2.1'
}


def boolean(value: Any) -> bool:
	if isinstance(value, str):
		if value.lower() in {'on', 'y', 'yes', 'true', 'enable', 'enabled', '1'}:
			return True

		if value.lower() in {'off', 'n', 'no', 'false', 'disable', 'disabled', '0'}:
			return False

		raise TypeError(f'Cannot parse string "{value}" as a boolean')

	if isinstance(value, int):
		if value == 1:
			return True

		if value == 0:
			return False

		raise ValueError('Integer value must be 1 or 0')

	if value is None:
		return False

	return bool(value)


def check_open_port(host: str, port: int) -> bool:
	if host == '0.0.0.0':
		host = '127.0.0.1'

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		try:
			return s.connect_ex((host, port)) != 0

		except socket.error:
			return False


def get_app() -> Application:
	from .application import Application  # pylint: disable=import-outside-toplevel

	if not Application.DEFAULT:
		raise ValueError('No default application set')

	return Application.DEFAULT


class Message(ApMessage):
	@classmethod
	def new_actor(cls: type[Message],  # pylint: disable=arguments-differ
				host: str,
				pubkey: str,
				description: str | None = None) -> Message:

		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'id': f'https://{host}/actor',
			'type': 'Application',
			'preferredUsername': 'relay',
			'name': 'ActivityRelay',
			'summary': description or 'ActivityRelay bot',
			'followers': f'https://{host}/followers',
			'following': f'https://{host}/following',
			'inbox': f'https://{host}/inbox',
			'url': f'https://{host}/',
			'endpoints': {
				'sharedInbox': f'https://{host}/inbox'
			},
			'publicKey': {
				'id': f'https://{host}/actor#main-key',
				'owner': f'https://{host}/actor',
				'publicKeyPem': pubkey
			}
		})


	@classmethod
	def new_announce(cls: type[Message], host: str, obj: str) -> Message:
		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'id': f'https://{host}/activities/{uuid4()}',
			'type': 'Announce',
			'to': [f'https://{host}/followers'],
			'actor': f'https://{host}/actor',
			'object': obj
		})


	@classmethod
	def new_follow(cls: type[Message], host: str, actor: str) -> Message:
		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'type': 'Follow',
			'to': [actor],
			'object': actor,
			'id': f'https://{host}/activities/{uuid4()}',
			'actor': f'https://{host}/actor'
		})


	@classmethod
	def new_unfollow(cls: type[Message], host: str, actor: str, follow: str) -> Message:
		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'id': f'https://{host}/activities/{uuid4()}',
			'type': 'Undo',
			'to': [actor],
			'actor': f'https://{host}/actor',
			'object': follow
		})


	@classmethod
	def new_response(cls: type[Message],
					host: str,
					actor: str,
					followid: str,
					accept: bool) -> Message:

		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'id': f'https://{host}/activities/{uuid4()}',
			'type': 'Accept' if accept else 'Reject',
			'to': [actor],
			'actor': f'https://{host}/actor',
			'object': {
				'id': followid,
				'type': 'Follow',
				'object': f'https://{host}/actor',
				'actor': actor
			}
		})


	# todo: remove when fixed in aputils
	@property
	def object_id(self) -> str:
		try:
			return self["object"]["id"]

		except (KeyError, TypeError):
			return self["object"]


class Response(AiohttpResponse):
	# AiohttpResponse.__len__ method returns 0, so bool(response) always returns False
	def __bool__(self) -> bool:
		return True


	@classmethod
	def new(cls: type[Response],
			body: str | bytes | dict = '',
			status: int = 200,
			headers: dict[str, str] | None = None,
			ctype: str = 'text') -> Response:

		kwargs = {
			'status': status,
			'headers': headers,
			'content_type': MIMETYPES[ctype]
		}

		if isinstance(body, bytes):
			kwargs['body'] = body

		elif isinstance(body, dict) and ctype in {'json', 'activity'}:
			kwargs['text'] = json.dumps(body)

		else:
			kwargs['text'] = body

		return cls(**kwargs)


	@classmethod
	def new_error(cls: type[Response],
				status: int,
				body: str | bytes | dict,
				ctype: str = 'text') -> Response:

		if ctype == 'json':
			body = json.dumps({'status': status, 'error': body})

		return cls.new(body=body, status=status, ctype=ctype)


	@property
	def location(self) -> str:
		return self.headers.get('Location')


	@location.setter
	def location(self, value: str) -> None:
		self.headers['Location'] = value


class View(AbstractView):
	def __await__(self) -> Generator[Response]:
		if (self.request.method) not in METHODS:
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods)

		if not (handler := self.handlers.get(self.request.method)):
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods) from None

		return self._run_handler(handler).__await__()


	async def _run_handler(self, handler: Awaitable) -> Response:
		with self.database.config.connection_class(self.database) as conn:
			# todo: remove on next tinysql release
			conn.open()

			return await handler(self.request, conn, **self.request.match_info)


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
