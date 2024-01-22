from __future__ import annotations

import json
import os
import typing
import yaml

from functools import cached_property
from pathlib import Path
from urllib.parse import urlparse

from . import logger as logging
from .misc import Message, boolean

if typing.TYPE_CHECKING:
	from typing import Any, Iterator, Optional


# pylint: disable=duplicate-code

class RelayConfig(dict):
	def __init__(self, path: str):
		dict.__init__(self, {})

		if self.is_docker:
			path = '/data/config.yaml'

		self._path = Path(path).expanduser().resolve()
		self.reset()


	def __setitem__(self, key: str, value: Any) -> None:
		if key in ['blocked_instances', 'blocked_software', 'whitelist']:
			assert isinstance(value, (list, set, tuple))

		elif key in ['port', 'workers', 'json_cache', 'timeout']:
			if not isinstance(value, int):
				value = int(value)

		elif key == 'whitelist_enabled':
			if not isinstance(value, bool):
				value = boolean(value)

		super().__setitem__(key, value)


	@property
	def db(self) -> RelayDatabase:
		return Path(self['db']).expanduser().resolve()


	@property
	def actor(self) -> str:
		return f'https://{self["host"]}/actor'


	@property
	def inbox(self) -> str:
		return f'https://{self["host"]}/inbox'


	@property
	def keyid(self) -> str:
		return f'{self.actor}#main-key'


	@cached_property
	def is_docker(self) -> bool:
		return bool(os.environ.get('DOCKER_RUNNING'))


	def reset(self) -> None:
		self.clear()
		self.update({
			'db': str(self._path.parent.joinpath(f'{self._path.stem}.jsonld')),
			'listen': '0.0.0.0',
			'port': 8080,
			'note': 'Make a note about your instance here.',
			'push_limit': 512,
			'json_cache': 1024,
			'timeout': 10,
			'workers': 0,
			'host': 'relay.example.com',
			'whitelist_enabled': False,
			'blocked_software': [],
			'blocked_instances': [],
			'whitelist': []
		})


	def load(self) -> None:
		self.reset()

		options = {}

		try:
			options['Loader'] = yaml.FullLoader

		except AttributeError:
			pass

		try:
			with self._path.open('r', encoding = 'UTF-8') as fd:
				config = yaml.load(fd, **options)

		except FileNotFoundError:
			return

		if not config:
			return

		for key, value in config.items():
			if key in ['ap']:
				for k, v in value.items():
					if k not in self:
						continue

					self[k] = v

				continue

			if key not in self:
				continue

			self[key] = value


class RelayDatabase(dict):
	def __init__(self, config: RelayConfig):
		dict.__init__(self, {
			'relay-list': {},
			'private-key': None,
			'follow-requests': {},
			'version': 1
		})

		self.config = config
		self.signer = None


	@property
	def hostnames(self) -> tuple[str]:
		return tuple(self['relay-list'].keys())


	@property
	def inboxes(self) -> tuple[dict[str, str]]:
		return tuple(data['inbox'] for data in self['relay-list'].values())


	def load(self) -> None:
		try:
			with self.config.db.open() as fd:
				data = json.load(fd)

			self['version'] = data.get('version', None)
			self['private-key'] = data.get('private-key')

			if self['version'] is None:
				self['version'] = 1

				if 'actorKeys' in data:
					self['private-key'] = data['actorKeys']['privateKey']

				for item in data.get('relay-list', []):
					domain = urlparse(item).hostname
					self['relay-list'][domain] = {
						'domain': domain,
						'inbox': item,
						'followid': None
					}

			else:
				self['relay-list'] = data.get('relay-list', {})

			for domain, instance in self['relay-list'].items():
				if not instance.get('domain'):
					instance['domain'] = domain

		except FileNotFoundError:
			pass

		except json.decoder.JSONDecodeError as e:
			if self.config.db.stat().st_size > 0:
				raise e from None


	def save(self) -> None:
		with self.config.db.open('w', encoding = 'UTF-8') as fd:
			json.dump(self, fd, indent=4)


	def get_inbox(self, domain: str, fail: Optional[bool] = False) -> dict[str, str] | None:
		if domain.startswith('http'):
			domain = urlparse(domain).hostname

		if (inbox := self['relay-list'].get(domain)):
			return inbox

		if fail:
			raise KeyError(domain)

		return None


	def add_inbox(self,
				inbox: str,
				followid: Optional[str] = None,
				software: Optional[str] = None) -> dict[str, str]:

		assert inbox.startswith('https'), 'Inbox must be a url'
		domain = urlparse(inbox).hostname
		instance = self.get_inbox(domain)

		if instance:
			if followid:
				instance['followid'] = followid

			if software:
				instance['software'] = software

			return instance

		self['relay-list'][domain] = {
			'domain': domain,
			'inbox': inbox,
			'followid': followid,
			'software': software
		}

		logging.verbose('Added inbox to database: %s', inbox)
		return self['relay-list'][domain]


	def del_inbox(self,
				domain: str,
				followid: Optional[str] = None,
				fail: Optional[bool] = False) -> bool:

		data = self.get_inbox(domain, fail=False)

		if not data:
			if fail:
				raise KeyError(domain)

			return False

		if not data['followid'] or not followid or data['followid'] == followid:
			del self['relay-list'][data['domain']]
			logging.verbose('Removed inbox from database: %s', data['inbox'])
			return True

		if fail:
			raise ValueError('Follow IDs do not match')

		logging.debug('Follow ID does not match: db = %s, object = %s', data['followid'], followid)
		return False


	def get_request(self, domain: str, fail: bool = True) -> dict[str, str] | None:
		if domain.startswith('http'):
			domain = urlparse(domain).hostname

		try:
			return self['follow-requests'][domain]

		except KeyError as e:
			if fail:
				raise e

			return None


	def add_request(self, actor: str, inbox: str, followid: str) -> None:
		domain = urlparse(inbox).hostname

		try:
			request = self.get_request(domain)
			request['followid'] = followid

		except KeyError:
			pass

		self['follow-requests'][domain] = {
			'actor': actor,
			'inbox': inbox,
			'followid': followid
		}


	def del_request(self, domain: str) -> None:
		if domain.startswith('http'):
			domain = urlparse(domain).hostname

		del self['follow-requests'][domain]


	def distill_inboxes(self, message: Message) -> Iterator[str]:
		src_domains = {
			message.domain,
			urlparse(message.object_id).netloc
		}

		for domain, instance in self['relay-list'].items():
			if domain not in src_domains:
				yield instance['inbox']
