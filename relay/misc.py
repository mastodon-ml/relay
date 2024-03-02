from __future__ import annotations

import aputils
import json
import os
import socket
import typing

from aiohttp.web import Response as AiohttpResponse
from datetime import datetime
from uuid import uuid4

try:
	from importlib.resources import files as pkgfiles

except ImportError:
	from importlib_resources import files as pkgfiles

if typing.TYPE_CHECKING:
	from pathlib import Path
	from typing import Any
	from .application import Application


IS_DOCKER = bool(os.environ.get('DOCKER_RUNNING'))
MIMETYPES = {
	'activity': 'application/activity+json',
	'css': 'text/css',
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


def get_resource(path: str) -> Path:
	return pkgfiles('relay').joinpath(path)


class JsonEncoder(json.JSONEncoder):
	def default(self, o: Any) -> str:
		if isinstance(o, datetime):
			return o.isoformat()

		return json.JSONEncoder.default(self, o)


class Message(aputils.Message):
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

		elif isinstance(body, (dict, list, tuple, set)) or ctype in {'json', 'activity'}:
			kwargs['text'] = json.dumps(body, cls = JsonEncoder)

		else:
			kwargs['text'] = body

		return cls(**kwargs)


	@classmethod
	def new_error(cls: type[Response],
				status: int,
				body: str | bytes | dict,
				ctype: str = 'text') -> Response:

		if ctype == 'json':
			body = {'error': body}

		return cls.new(body=body, status=status, ctype=ctype)


	@classmethod
	def new_redir(cls: type[Response], path: str) -> Response:
		body = f'Redirect to <a href="{path}">{path}</a>'
		return cls.new(body, 302, {'Location': path})


	@property
	def location(self) -> str:
		return self.headers.get('Location')


	@location.setter
	def location(self, value: str) -> None:
		self.headers['Location'] = value
