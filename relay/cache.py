from __future__ import annotations

import json
import os
import typing

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from redis import Redis

from .misc import Message, boolean

if typing.TYPE_CHECKING:
	from typing import Any
	from collections.abc import Callable, Iterator
	from tinysql import Database
	from .application import Application


# todo: implement more caching backends


BACKENDS: dict[str, Cache] = {}
CONVERTERS: dict[str, tuple[Callable, Callable]] = {
	'str': (str, str),
	'int': (str, int),
	'bool': (str, boolean),
	'json': (json.dumps, json.loads),
	'message': (lambda x: x.to_json(), Message.parse)
}


def get_cache(app: Application) -> Cache:
	return BACKENDS[app.config.ca_type](app)


def register_cache(backend: type[Cache]) -> type[Cache]:
	BACKENDS[backend.name] = backend
	return backend


def serialize_value(value: Any, value_type: str = 'str') -> str:
	if isinstance(value, str):
		return value

	return CONVERTERS[value_type][0](value)


def deserialize_value(value: str, value_type: str = 'str') -> Any:
	return CONVERTERS[value_type][1](value)


@dataclass
class Item:
	namespace: str
	key: str
	value: Any
	value_type: str
	updated: datetime


	def __post_init__(self):
		if isinstance(self.updated, str):
			self.updated = datetime.fromisoformat(self.updated)


	@classmethod
	def from_data(cls: type[Item], *args) -> Item:
		data = cls(*args)
		data.value = deserialize_value(data.value, data.value_type)
		data.updated = datetime.fromtimestamp(data.updated, tz = timezone.utc)
		return data


	def older_than(self, hours: int) -> bool:
		delta = datetime.now(tz = timezone.utc) - self.updated
		return (delta.total_seconds()) > hours * 3600


	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


class Cache(ABC):
	name: str = 'null'


	def __init__(self, app: Application):
		self.app = app
		self.setup()

	@abstractmethod
	def get(self, namespace: str, key: str) -> Item:
		...


	@abstractmethod
	def get_keys(self, namespace: str) -> Iterator[str]:
		...


	@abstractmethod
	def get_namespaces(self) -> Iterator[str]:
		...


	@abstractmethod
	def set(self, namespace: str, key: str, value: Any, value_type: str = 'key') -> Item:
		...


	@abstractmethod
	def delete(self, namespace: str, key: str) -> None:
		...


	@abstractmethod
	def setup(self) -> None:
		...


	def set_item(self, item: Item) -> Item:
		return self.set(
			item.namespace,
			item.key,
			item.value,
			item.type
		)


	def delete_item(self, item: Item) -> None:
		self.delete(item.namespace, item.key)


@register_cache
class SqlCache(Cache):
	name: str = 'database'


	@property
	def _db(self) -> Database:
		return self.app.database


	def get(self, namespace: str, key: str) -> Item:
		params = {
			'namespace': namespace,
			'key': key
		}

		with self._db.connection() as conn:
			with conn.exec_statement('get-cache-item', params) as cur:
				if not (row := cur.one()):
					raise KeyError(f'{namespace}:{key}')

				row.pop('id', None)
				return Item.from_data(*tuple(row.values()))


	def get_keys(self, namespace: str) -> Iterator[str]:
		with self._db.connection() as conn:
			for row in conn.exec_statement('get-cache-keys', {'namespace': namespace}):
				yield row['key']


	def get_namespaces(self) -> Iterator[str]:
		with self._db.connection() as conn:
			for row in conn.exec_statement('get-cache-namespaces', None):
				yield row['namespace']


	def set(self, namespace: str, key: str, value: Any, value_type: str = 'str') -> Item:
		params = {
			'namespace': namespace,
			'key': key,
			'value': serialize_value(value, value_type),
			'type': value_type,
			'date': datetime.now(tz = timezone.utc)
		}

		with self._db.connection() as conn:
			with conn.exec_statement('set-cache-item', params) as conn:
				row = conn.one()
				row.pop('id', None)
				return Item.from_data(*tuple(row.values()))


	def delete(self, namespace: str, key: str) -> None:
		params = {
			'namespace': namespace,
			'key': key
		}

		with self._db.connection() as conn:
			with conn.exec_statement('del-cache-item', params):
				pass


	def setup(self) -> None:
		with self._db.connection() as conn:
			with conn.exec_statement(f'create-cache-table-{self._db.type.name.lower()}', None):
				pass


@register_cache
class RedisCache(Cache):
	name: str = 'redis'
	_rd: Redis


	@property
	def prefix(self) -> str:
		return self.app.config.rd_prefix


	def get_key_name(self, namespace: str, key: str) -> str:
		return f'{self.prefix}:{namespace}:{key}'


	def get(self, namespace: str, key: str) -> Item:
		key_name = self.get_key_name(namespace, key)

		if not (raw_value := self._rd.get(key_name)):
			raise KeyError(f'{namespace}:{key}')

		value_type, updated, value = raw_value.split(':', 2)
		return Item.from_data(
			namespace,
			key,
			value,
			value_type,
			datetime.fromtimestamp(float(updated), tz = timezone.utc)
		)


	def get_keys(self, namespace: str) -> Iterator[str]:
		for key in self._rd.keys(self.get_key_name(namespace, '*')):
			*_, key_name = key.split(':', 2)
			yield key_name


	def get_namespaces(self) -> Iterator[str]:
		namespaces = []

		for key in self._rd.keys(f'{self.prefix}:*'):
			_, namespace, _ = key.split(':', 2)

			if namespace not in namespaces:
				namespaces.append(namespace)
				yield namespace


	def set(self, namespace: str, key: str, value: Any, value_type: str = 'key') -> None:
		date = datetime.now(tz = timezone.utc).timestamp()
		value = serialize_value(value, value_type)

		self._rd.set(
			self.get_key_name(namespace, key),
			f'{value_type}:{date}:{value}'
		)


	def delete(self, namespace: str, key: str) -> None:
		self._rd.delete(self.get_key_name(namespace, key))


	def setup(self) -> None:
		options = {
			'client_name': f'ActivityRelay_{self.app.config.domain}',
			'decode_responses': True,
			'username': self.app.config.rd_user,
			'password': self.app.config.rd_pass,
			'db': self.app.config.rd_database
		}

		if os.path.exists(self.app.config.rd_host):
			options['unix_socket_path'] = self.app.config.rd_host

		else:
			options['host'] = self.app.config.rd_host
			options['port'] = self.app.config.rd_port

		self._rd = Redis(**options)
