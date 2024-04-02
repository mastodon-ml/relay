from __future__ import annotations

import aputils
import json
import os
import platform
import socket
import typing

from aiohttp.web import Response as AiohttpResponse
from datetime import datetime
from pathlib import Path
from uuid import uuid4

try:
	from importlib.resources import files as pkgfiles

except ImportError:
	from importlib_resources import files as pkgfiles # type: ignore

if typing.TYPE_CHECKING:
	from typing import Any
	from .application import Application

	try:
		from typing import Self

	except ImportError:
		from typing_extensions import Self


T = typing.TypeVar('T')
ResponseType = typing.TypedDict('ResponseType', {
	'status': int,
	'headers': dict[str, typing.Any] | None,
	'content_type': str,
	'body': bytes | None,
	'text': str | None
})

IS_DOCKER = bool(os.environ.get('DOCKER_RUNNING'))
IS_WINDOWS = platform.system() == 'Windows'

MIMETYPES = {
	'activity': 'application/activity+json',
	'css': 'text/css',
	'html': 'text/html',
	'json': 'application/json',
	'text': 'text/plain',
	'webmanifest': 'application/manifest+json'
}

NODEINFO_NS = {
	'20': 'http://nodeinfo.diaspora.software/ns/schema/2.0',
	'21': 'http://nodeinfo.diaspora.software/ns/schema/2.1'
}

ACTOR_FORMATS = {
	'mastodon': 'https://{domain}/actor',
	'akkoma': 'https://{domain}/relay',
	'pleroma': 'https://{domain}/relay'
}

SOFTWARE = (
	'mastodon',
	'akkoma',
	'pleroma',
	'misskey',
	'friendica',
	'hubzilla',
	'firefish',
	'gotosocial'
)


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
	from .application import Application

	if not Application.DEFAULT:
		raise ValueError('No default application set')

	return Application.DEFAULT


def get_resource(path: str) -> Path:
	return Path(str(pkgfiles('relay'))).joinpath(path)


class JsonEncoder(json.JSONEncoder):
	def default(self, o: Any) -> str:
		if isinstance(o, datetime):
			return o.isoformat()

		return json.JSONEncoder.default(self, o)


class Message(aputils.Message):
	@classmethod
	def new_actor(cls: type[Self], # type: ignore
				host: str,
				pubkey: str,
				description: str | None = None,
				approves: bool = False) -> Self:

		return cls.new(aputils.ObjectType.APPLICATION, {
			'id': f'https://{host}/actor',
			'preferredUsername': 'relay',
			'name': 'ActivityRelay',
			'summary': description or 'ActivityRelay bot',
			'manuallyApprovesFollowers': approves,
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
	def new_announce(cls: type[Self], host: str, obj: str | dict[str, Any]) -> Self:
		return cls.new(aputils.ObjectType.ANNOUNCE, {
			'id': f'https://{host}/activities/{uuid4()}',
			'to': [f'https://{host}/followers'],
			'actor': f'https://{host}/actor',
			'object': obj
		})


	@classmethod
	def new_follow(cls: type[Self], host: str, actor: str) -> Self:
		return cls.new(aputils.ObjectType.FOLLOW, {
			'id': f'https://{host}/activities/{uuid4()}',
			'to': [actor],
			'object': actor,
			'actor': f'https://{host}/actor'
		})


	@classmethod
	def new_unfollow(cls: type[Self], host: str, actor: str, follow: dict[str, str]) -> Self:
		return cls.new(aputils.ObjectType.UNDO, {
			'id': f'https://{host}/activities/{uuid4()}',
			'to': [actor],
			'actor': f'https://{host}/actor',
			'object': follow
		})


	@classmethod
	def new_response(cls: type[Self], host: str, actor: str, followid: str, accept: bool) -> Self:
		return cls.new(aputils.ObjectType.ACCEPT if accept else aputils.ObjectType.REJECT, {
			'id': f'https://{host}/activities/{uuid4()}',
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
	def new(cls: type[Self],
			body: str | bytes | dict | tuple | list | set = '',
			status: int = 200,
			headers: dict[str, str] | None = None,
			ctype: str = 'text') -> Self:

		kwargs: ResponseType = {
			'status': status,
			'headers': headers,
			'content_type': MIMETYPES[ctype],
			'body': None,
			'text': None
		}

		if isinstance(body, bytes):
			kwargs['body'] = body

		elif isinstance(body, (dict, list, tuple, set)) or ctype in {'json', 'activity'}:
			kwargs['text'] = json.dumps(body, cls = JsonEncoder)

		else:
			kwargs['text'] = body

		return cls(**kwargs)


	@classmethod
	def new_error(cls: type[Self],
				status: int,
				body: str | bytes | dict,
				ctype: str = 'text') -> Self:

		if ctype == 'json':
			body = {'error': body}

		return cls.new(body=body, status=status, ctype=ctype)


	@classmethod
	def new_redir(cls: type[Self], path: str) -> Self:
		body = f'Redirect to <a href="{path}">{path}</a>'
		return cls.new(body, 302, {'Location': path})


	@property
	def location(self) -> str:
		return self.headers.get('Location', '')


	@location.setter
	def location(self, value: str) -> None:
		self.headers['Location'] = value
