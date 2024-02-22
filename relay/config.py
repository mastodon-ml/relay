from __future__ import annotations

import getpass
import os
import platform
import typing
import yaml

from pathlib import Path

from .misc import IS_DOCKER

if typing.TYPE_CHECKING:
	from typing import Any


if platform.system() == 'Windows':
	import multiprocessing
	CORE_COUNT = multiprocessing.cpu_count()

else:
	CORE_COUNT = len(os.sched_getaffinity(0))


DEFAULTS: dict[str, Any] = {
	'listen': '0.0.0.0',
	'port': 8080,
	'domain': 'relay.example.com',
	'workers': CORE_COUNT,
	'db_type': 'sqlite',
	'ca_type': 'database',
	'sq_path': 'relay.sqlite3',

	'pg_host': '/var/run/postgresql',
	'pg_port': 5432,
	'pg_user': getpass.getuser(),
	'pg_pass': None,
	'pg_name': 'activityrelay',

	'rd_host': 'localhost',
	'rd_port': 6379,
	'rd_user': None,
	'rd_pass': None,
	'rd_database': 0,
	'rd_prefix': 'activityrelay'
}

if IS_DOCKER:
	DEFAULTS['sq_path'] = '/data/relay.jsonld'


class Config:
	def __init__(self, path: str, load: bool = False):
		self.path = Path(path).expanduser().resolve()

		self.listen = None
		self.port = None
		self.domain = None
		self.workers = None
		self.db_type = None
		self.ca_type = None
		self.sq_path = None

		self.pg_host = None
		self.pg_port = None
		self.pg_user = None
		self.pg_pass = None
		self.pg_name = None

		self.rd_host = None
		self.rd_port = None
		self.rd_user = None
		self.rd_pass = None
		self.rd_database = None
		self.rd_prefix = None

		if load:
			try:
				self.load()

			except FileNotFoundError:
				self.save()


	@property
	def sqlite_path(self) -> Path:
		if not os.path.isabs(self.sq_path):
			return self.path.parent.joinpath(self.sq_path).resolve()

		return Path(self.sq_path).expanduser().resolve()


	@property
	def actor(self) -> str:
		return f'https://{self.domain}/actor'


	@property
	def inbox(self) -> str:
		return f'https://{self.domain}/inbox'


	@property
	def keyid(self) -> str:
		return f'{self.actor}#main-key'


	def load(self) -> None:
		self.reset()

		options = {}

		try:
			options['Loader'] = yaml.FullLoader

		except AttributeError:
			pass

		with self.path.open('r', encoding = 'UTF-8') as fd:
			config = yaml.load(fd, **options)
			pgcfg = config.get('postgresql', {})
			rdcfg = config.get('redis', {})

		if not config:
			raise ValueError('Config is empty')

		if IS_DOCKER:
			self.listen = '0.0.0.0'
			self.port = 8080
			self.sq_path = '/data/relay.jsonld'

		else:
			self.set('listen', config.get('listen', DEFAULTS['listen']))
			self.set('port', config.get('port', DEFAULTS['port']))
			self.set('sq_path', config.get('sqlite_path', DEFAULTS['sq_path']))

		self.set('workers', config.get('workers', DEFAULTS['workers']))
		self.set('domain', config.get('domain', DEFAULTS['domain']))
		self.set('db_type', config.get('database_type', DEFAULTS['db_type']))
		self.set('ca_type', config.get('cache_type', DEFAULTS['ca_type']))

		for key in DEFAULTS:
			if key.startswith('pg'):
				try:
					self.set(key, pgcfg[key[3:]])

				except KeyError:
					continue

			elif key.startswith('rd'):
				try:
					self.set(key, rdcfg[key[3:]])

				except KeyError:
					continue


	def reset(self) -> None:
		for key, value in DEFAULTS.items():
			setattr(self, key, value)


	def save(self) -> None:
		self.path.parent.mkdir(exist_ok = True, parents = True)

		config = {
			'listen': self.listen,
			'port': self.port,
			'domain': self.domain,
			'workers': self.workers,
			'database_type': self.db_type,
			'cache_type': self.ca_type,
			'sqlite_path': self.sq_path,
			'postgres': {
				'host': self.pg_host,
				'port': self.pg_port,
				'user': self.pg_user,
				'pass': self.pg_pass,
				'name': self.pg_name
			},
			'redis': {
				'host': self.rd_host,
				'port': self.rd_port,
				'user': self.rd_user,
				'pass': self.rd_pass,
				'database': self.rd_database,
				'refix': self.rd_prefix
			}
		}

		with self.path.open('w', encoding = 'utf-8') as fd:
			yaml.dump(config, fd, sort_keys = False)


	def set(self, key: str, value: Any) -> None:
		if key not in DEFAULTS:
			raise KeyError(key)

		if key in {'port', 'pg_port', 'workers'} and not isinstance(value, int):
			if (value := int(value)) < 1:
				if key == 'port':
					value = 8080

				elif key == 'pg_port':
					value = 5432

				elif key == 'workers':
					value = len(os.sched_getaffinity(0))

		setattr(self, key, value)
