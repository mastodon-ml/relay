from __future__ import annotations

import getpass
import os
import platform
import yaml

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from platformdirs import user_config_dir
from typing import TYPE_CHECKING, Any

from .misc import IS_DOCKER

if TYPE_CHECKING:
	from typing import Self


if platform.system() == 'Windows':
	import multiprocessing
	CORE_COUNT = multiprocessing.cpu_count()

else:
	CORE_COUNT = len(os.sched_getaffinity(0))


DOCKER_VALUES = {
	'listen': '0.0.0.0',
	'port': 8080,
	'sq_path': '/data/relay.sqlite3'
}


class NOVALUE:
	pass


@dataclass(init = False)
class Config:
	listen: str = '0.0.0.0'
	port: int = 8080
	domain: str = 'relay.example.com'
	workers: int = CORE_COUNT
	db_type: str = 'sqlite'
	ca_type: str = 'database'
	sq_path: str = 'relay.sqlite3'

	pg_host: str = '/var/run/postgresql'
	pg_port: int = 5432
	pg_user: str = getpass.getuser()
	pg_pass: str | None = None
	pg_name: str = 'activityrelay'

	rd_host: str = 'localhost'
	rd_port: int = 6470
	rd_user: str | None = None
	rd_pass: str | None = None
	rd_database: int = 0
	rd_prefix: str = 'activityrelay'


	def __init__(self, path: Path | None = None, load: bool = False):
		self.path: Path = Config.get_config_dir(path)
		self.reset()

		if load:
			try:
				self.load()

			except FileNotFoundError:
				self.save()


	@classmethod
	def KEYS(cls: type[Self]) -> list[str]:
		return list(cls.__dataclass_fields__)


	@classmethod
	def DEFAULT(cls: type[Self], key: str) -> str | int | None:
		for field in fields(cls):
			if field.name == key:
				return field.default # type: ignore[return-value]

		raise KeyError(key)


	@staticmethod
	def get_config_dir(path: Path | str | None = None) -> Path:
		if isinstance(path, str):
			path = Path(path)

		if path is not None:
			return path.expanduser().resolve()

		paths = (
			Path("relay.yaml").resolve(),
			Path(user_config_dir("activityrelay"), "relay.yaml"),
			Path("/etc/activityrelay/relay.yaml")
		)

		for cfgfile in paths:
			if cfgfile.exists():
				return cfgfile

		return paths[0]


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

		if not config:
			raise ValueError('Config is empty')

		pgcfg = config.get('postgres', {})
		rdcfg = config.get('redis', {})

		for key in type(self).KEYS():
			if IS_DOCKER and key in {'listen', 'port', 'sq_path'}:
				self.set(key, DOCKER_VALUES[key])
				continue

			if key.startswith('pg'):
				self.set(key, pgcfg.get(key[3:], NOVALUE))
				continue

			elif key.startswith('rd'):
				self.set(key, rdcfg.get(key[3:], NOVALUE))
				continue

			cfgkey = key

			if key == 'db_type':
				cfgkey = 'database_type'

			elif key == 'ca_type':
				cfgkey = 'cache_type'

			elif key == 'sq_path':
				cfgkey = 'sqlite_path'

			self.set(key, config.get(cfgkey, NOVALUE))


	def reset(self) -> None:
		for field in fields(self):
			setattr(self, field.name, field.default)


	def save(self) -> None:
		self.path.parent.mkdir(exist_ok = True, parents = True)

		data: dict[str, Any] = {}

		for key, value in asdict(self).items():
			if key.startswith('pg_'):
				if 'postgres' not in data:
					data['postgres'] = {}

				data['postgres'][key[3:]] = value
				continue

			if key.startswith('rd_'):
				if 'redis' not in data:
					data['redis'] = {}

				data['redis'][key[3:]] = value
				continue

			if key == 'db_type':
				key = 'database_type'

			elif key == 'ca_type':
				key = 'cache_type'

			elif key == 'sq_path':
				key = 'sqlite_path'

			data[key] = value

		with self.path.open('w', encoding = 'utf-8') as fd:
			yaml.dump(data, fd, sort_keys = False)


	def set(self, key: str, value: Any) -> None:
		if key not in type(self).KEYS():
			raise KeyError(key)

		if value is NOVALUE:
			return

		setattr(self, key, value)
