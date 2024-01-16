from __future__ import annotations

import json
import socket
import traceback
import typing

from aiohttp.abc import AbstractView
from aiohttp.hdrs import METH_ALL as METHODS
from aiohttp.web import Request as AiohttpRequest, Response as AiohttpResponse
from aiohttp.web_exceptions import HTTPMethodNotAllowed
from aputils.errors import SignatureFailureError
from aputils.misc import Digest, HttpDate, Signature
from aputils.message import Message as ApMessage
from functools import cached_property
from json.decoder import JSONDecodeError
from uuid import uuid4

from . import logger as logging

if typing.TYPE_CHECKING:
	from typing import Any, Coroutine, Generator, Optional, Type
	from aputils.signer import Signer
	from .application import Application
	from .config import RelayConfig
	from .database import RelayDatabase
	from .http_client import HttpClient


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
		if value.lower() in ['on', 'y', 'yes', 'true', 'enable', 'enabled', '1']:
			return True

		if value.lower() in ['off', 'n', 'no', 'false', 'disable', 'disable', '0']:
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


class DotDict(dict):
	def __init__(self, _data: dict[str, Any], **kwargs: Any):
		dict.__init__(self)

		self.update(_data, **kwargs)


	def __getattr__(self, key: str) -> str:
		try:
			return self[key]

		except KeyError:
			raise AttributeError(
				f'{self.__class__.__name__} object has no attribute {key}'
			) from None


	def __setattr__(self, key: str, value: Any) -> None:
		if key.startswith('_'):
			super().__setattr__(key, value)

		else:
			self[key] = value


	def __setitem__(self, key: str, value: Any) -> None:
		if type(value) is dict:  # pylint: disable=unidiomatic-typecheck
			value = DotDict(value)

		super().__setitem__(key, value)


	def __delattr__(self, key: str) -> None:
		try:
			dict.__delitem__(self, key)

		except KeyError:
			raise AttributeError(
				f'{self.__class__.__name__} object has no attribute {key}'
			) from None


	@classmethod
	def new_from_json(cls: Type[DotDict], data: dict[str, Any]) -> DotDict[str, Any]:
		if not data:
			raise JSONDecodeError('Empty body', data, 1)

		try:
			return cls(json.loads(data))

		except ValueError:
			raise JSONDecodeError('Invalid body', data, 1) from None


	@classmethod
	def new_from_signature(cls: Type[DotDict], sig: str) -> DotDict[str, Any]:
		data = cls({})

		for chunk in sig.strip().split(','):
			key, value = chunk.split('=', 1)
			value = value.strip('\"')

			if key == 'headers':
				value = value.split()

			data[key.lower()] = value

		return data


	def to_json(self, indent: Optional[int | str] = None) -> str:
		return json.dumps(self, indent=indent)


	def update(self, _data: dict[str, Any], **kwargs: Any) -> None:
		if isinstance(_data, dict):
			for key, value in _data.items():
				self[key] = value

		elif isinstance(_data, (list, tuple, set)):
			for key, value in _data:
				self[key] = value

		for key, value in kwargs.items():
			self[key] = value


class Message(ApMessage):
	@classmethod
	def new_actor(cls: Type[Message],  # pylint: disable=arguments-differ
				host: str,
				pubkey: str,
				description: Optional[str] = None) -> Message:

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
			'url': f'https://{host}/inbox',
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
	def new_announce(cls: Type[Message], host: str, obj: str) -> Message:
		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'id': f'https://{host}/activities/{uuid4()}',
			'type': 'Announce',
			'to': [f'https://{host}/followers'],
			'actor': f'https://{host}/actor',
			'object': obj
		})


	@classmethod
	def new_follow(cls: Type[Message], host: str, actor: str) -> Message:
		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'type': 'Follow',
			'to': [actor],
			'object': actor,
			'id': f'https://{host}/activities/{uuid4()}',
			'actor': f'https://{host}/actor'
		})


	@classmethod
	def new_unfollow(cls: Type[Message], host: str, actor: str, follow: str) -> Message:
		return cls({
			'@context': 'https://www.w3.org/ns/activitystreams',
			'id': f'https://{host}/activities/{uuid4()}',
			'type': 'Undo',
			'to': [actor],
			'actor': f'https://{host}/actor',
			'object': follow
		})


	@classmethod
	def new_response(cls: Type[Message],
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
	@classmethod
	def new(cls: Type[Response],
			body: Optional[str | bytes | dict] = '',
			status: Optional[int] = 200,
			headers: Optional[dict[str, str]] = None,
			ctype: Optional[str] = 'text') -> Response:

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
	def new_error(cls: Type[Response],
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
	def __init__(self, request: AiohttpRequest):
		AbstractView.__init__(self, request)

		self.signature: Signature = None
		self.message: Message = None
		self.actor: Message = None
		self.instance: dict[str, str] = None
		self.signer: Signer = None


	def __await__(self) -> Generator[Response]:
		method = self.request.method.upper()

		if method not in METHODS:
			raise HTTPMethodNotAllowed(method, self.allowed_methods)

		if not (handler := self.handlers.get(method)):
			raise HTTPMethodNotAllowed(self.request.method, self.allowed_methods) from None

		return handler(self.request, **self.request.match_info).__await__()


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
	def client(self) -> HttpClient:
		return self.app.client


	@property
	def config(self) -> RelayConfig:
		return self.app.config


	@property
	def database(self) -> RelayDatabase:
		return self.app.database


	# todo: move to views.ActorView
	async def get_post_data(self) -> Response | None:
		try:
			self.signature = Signature.new_from_signature(self.request.headers['signature'])

		except KeyError:
			logging.verbose('Missing signature header')
			return Response.new_error(400, 'missing signature header', 'json')

		try:
			self.message = await self.request.json(loads = Message.parse)

		except Exception:
			traceback.print_exc()
			logging.verbose('Failed to parse inbox message')
			return Response.new_error(400, 'failed to parse message', 'json')

		if self.message is None:
			logging.verbose('empty message')
			return Response.new_error(400, 'missing message', 'json')

		if 'actor' not in self.message:
			logging.verbose('actor not in message')
			return Response.new_error(400, 'no actor in message', 'json')

		self.actor = await self.client.get(self.signature.keyid, sign_headers = True)

		if self.actor is None:
			# ld signatures aren't handled atm, so just ignore it
			if self.message.type == 'Delete':
				logging.verbose('Instance sent a delete which cannot be handled')
				return Response.new(status=202)

			logging.verbose(f'Failed to fetch actor: {self.signature.keyid}')
			return Response.new_error(400, 'failed to fetch actor', 'json')

		try:
			self.signer = self.actor.signer

		except KeyError:
			logging.verbose('Actor missing public key: %s', self.signature.keyid)
			return Response.new_error(400, 'actor missing public key', 'json')

		try:
			self.validate_signature(await self.request.read())

		except SignatureFailureError as e:
			logging.verbose('signature validation failed for "%s": %s', self.actor.id, e)
			return Response.new_error(401, str(e), 'json')

		self.instance = self.database.get_inbox(self.actor.inbox)


	def validate_signature(self, body: bytes) -> None:
		headers = {key.lower(): value for key, value in self.request.headers.items()}
		headers["(request-target)"] = " ".join([self.request.method.lower(), self.request.path])

		if (digest := Digest.new_from_digest(headers.get("digest"))):
			if not body:
				raise SignatureFailureError("Missing body for digest verification")

			if not digest.validate(body):
				raise SignatureFailureError("Body digest does not match")

		if self.signature.algorithm_type == "hs2019":
			if "(created)" not in self.signature.headers:
				raise SignatureFailureError("'(created)' header not used")

			current_timestamp = HttpDate.new_utc().timestamp()

			if self.signature.created > current_timestamp:
				raise SignatureFailureError("Creation date after current date")

			if current_timestamp > self.signature.expires:
				raise SignatureFailureError("Expiration date before current date")

			headers["(created)"] = self.signature.created
			headers["(expires)"] = self.signature.expires

		# pylint: disable=protected-access
		if not self.signer._validate_signature(headers, self.signature):
			raise SignatureFailureError("Signature does not match")
