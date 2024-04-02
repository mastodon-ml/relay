from __future__ import annotations

import json
import os
import typing

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from redis import Redis

from .database import get_database
from .misc import Message, boolean

if typing.TYPE_CHECKING:
	from blib import Database
	from collections.abc import Callable, Iterator
	from typing import Any
	from .application import Application


# todo: implement more caching backends


BACKENDS: dict[str, type[Cache]] = {}
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

		if not isinstance(data.updated, datetime):
			data.updated = datetime.fromtimestamp(data.updated, tz = timezone.utc) # type: ignore

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
	def delete_old(self, days: int = 14) -> None:
		...


	@abstractmethod
	def clear(self) -> None:
		...


	@abstractmethod
	def setup(self) -> None:
		...


	@abstractmethod
	def close(self) -> None:
		...


	def set_item(self, item: Item) -> Item:
		return self.set(
			item.namespace,
			item.key,
			item.value,
			item.value_type
		)


	def delete_item(self, item: Item) -> None:
		self.delete(item.namespace, item.key)


@register_cache
class SqlCache(Cache):
	name: str = 'database'


	def __init__(self, app: Application):
		Cache.__init__(self, app)
		self._db: Database = None


	def get(self, namespace: str, key: str) -> Item:
		params = {
			'namespace': namespace,
			'key': key
		}

		with self._db.session(False) as conn:
			with conn.run('get-cache-item', params) as cur:
				if not (row := cur.one()):
					raise KeyError(f'{namespace}:{key}')

				row.pop('id', None)
				return Item.from_data(*tuple(row.values()))


	def get_keys(self, namespace: str) -> Iterator[str]:
		with self._db.session(False) as conn:
			for row in conn.run('get-cache-keys', {'namespace': namespace}):
				yield row['key']


	def get_namespaces(self) -> Iterator[str]:
		with self._db.session(False) as conn:
			for row in conn.run('get-cache-namespaces', None):
				yield row['namespace']


	def set(self, namespace: str, key: str, value: Any, value_type: str = 'str') -> Item:
		params = {
			'namespace': namespace,
			'key': key,
			'value': serialize_value(value, value_type),
			'type': value_type,
			'date': datetime.now(tz = timezone.utc)
		}

		with self._db.session(True) as conn:
			with conn.run('set-cache-item', params) as conn:
				row = conn.one()
				row.pop('id', None)
				return Item.from_data(*tuple(row.values()))


	def delete(self, namespace: str, key: str) -> None:
		params = {
			'namespace': namespace,
			'key': key
		}

		with self._db.session(True) as conn:
			with conn.run('del-cache-item', params):
				pass


	def delete_old(self, days: int = 14) -> None:
		limit = datetime.now(tz = timezone.utc) - timedelta(days = days)
		params = {"limit": limit.timestamp()}

		with self._db.session(True) as conn:
			with conn.execute("DELETE FROM cache WHERE updated < :limit", params):
				pass


	def clear(self) -> None:
		with self._db.session(True) as conn:
			with conn.execute("DELETE FROM cache"):
				pass


	def setup(self) -> None:
		if self._db and self._db.connected:
			return

		self._db = get_database(self.app.config)
		self._db.connect()

		with self._db.session(True) as conn:
			with conn.run(f'create-cache-table-{self._db.backend_type.value}', None):
				pass


	def close(self) -> None:
		if not self._db:
			return

		self._db.disconnect()
		self._db = None


@register_cache
class RedisCache(Cache):
	name: str = 'redis'


	def __init__(self, app: Application):
		Cache.__init__(self, app)
		self._rd: Redis = None # type: ignore


	@property
	def prefix(self) -> str:
		return self.app.config.rd_prefix


	def get_key_name(self, namespace: str, key: str) -> str:
		return f'{self.prefix}:{namespace}:{key}'


	def get(self, namespace: str, key: str) -> Item:
		key_name = self.get_key_name(namespace, key)

		if not (raw_value := self._rd.get(key_name)):
			raise KeyError(f'{namespace}:{key}')

		value_type, updated, value = raw_value.split(':', 2) # type: ignore
		return Item.from_data(
			namespace,
			key,
			value,
			value_type,
			datetime.fromtimestamp(float(updated), tz = timezone.utc)
		)


	def get_keys(self, namespace: str) -> Iterator[str]:
		for key in self._rd.scan_iter(self.get_key_name(namespace, '*')):
			*_, key_name = key.split(':', 2)
			yield key_name


	def get_namespaces(self) -> Iterator[str]:
		namespaces = []

		for key in self._rd.scan_iter(f'{self.prefix}:*'):
			_, namespace, _ = key.split(':', 2)

			if namespace not in namespaces:
				namespaces.append(namespace)
				yield namespace


	def set(self, namespace: str, key: str, value: Any, value_type: str = 'key') -> Item:
		date = datetime.now(tz = timezone.utc).timestamp()
		value = serialize_value(value, value_type)

		self._rd.set(
			self.get_key_name(namespace, key),
			f'{value_type}:{date}:{value}'
		)

		return self.get(namespace, key)


	def delete(self, namespace: str, key: str) -> None:
		self._rd.delete(self.get_key_name(namespace, key))


	def delete_old(self, days: int = 14) -> None:
		limit = datetime.now(tz = timezone.utc) - timedelta(days = days)

		for full_key in self._rd.scan_iter(f'{self.prefix}:*'):
			_, namespace, key = full_key.split(':', 2)
			item = self.get(namespace, key)

			if item.updated < limit:
				self.delete_item(item)


	def clear(self) -> None:
		self._rd.delete(f"{self.prefix}:*")


	def setup(self) -> None:
		if self._rd:
			return

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

		self._rd = Redis(**options) # type: ignore


	def close(self) -> None:
		if not self._rd:
			return

		self._rd.close()
		self._rd = None # type: ignore
