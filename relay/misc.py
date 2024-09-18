from __future__ import annotations

import aputils
import json
import os
import platform

from aiohttp.web import Response as AiohttpResponse
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict, TypeVar
from uuid import uuid4

if TYPE_CHECKING:
	from typing import Self
	from .application import Application


T = TypeVar('T')
ResponseType = TypedDict('ResponseType', {
	'status': int,
	'headers': dict[str, Any] | None,
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

JSON_PATHS: tuple[str, ...] = (
	'/api/v1',
	'/actor',
	'/inbox',
	'/outbox',
	'/following',
	'/followers',
	'/.well-known',
	'/nodeinfo',
	'/oauth/token',
	'/oauth/revoke'
)

TOKEN_PATHS: tuple[str, ...] = (
	'/logout',
	'/admin',
	'/api',
	'/oauth/authorize',
	'/oauth/revoke'
)


def get_app() -> Application:
	from .application import Application

	if not Application.DEFAULT:
		raise ValueError('No default application set')

	return Application.DEFAULT


class JsonEncoder(json.JSONEncoder):
	def default(self, o: Any) -> str:
		if isinstance(o, datetime):
			return o.isoformat()

		return json.JSONEncoder.default(self, o) # type: ignore[no-any-return]


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
			'outbox': f'https://{host}/outbox',
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
			body: str | bytes | dict[str, Any] | Sequence[Any] = '',
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

		if isinstance(body, str):
			kwargs['text'] = body

		elif isinstance(body, bytes):
			kwargs['body'] = body

		elif isinstance(body, (dict, Sequence)):
			kwargs['text'] = json.dumps(body, cls = JsonEncoder)

		return cls(**kwargs)


	@classmethod
	def new_redir(cls: type[Self], path: str, status: int = 307) -> Self:
		body = f'Redirect to <a href="{path}">{path}</a>'
		return cls.new(body, status, {'Location': path}, ctype = 'html')


	@property
	def location(self) -> str:
		return self.headers.get('Location', '')


	@location.setter
	def location(self, value: str) -> None:
		self.headers['Location'] = value
