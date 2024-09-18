from __future__ import annotations
# removing the above line turns annotations into types instead of str objects which messes with
# `Field.type`

from blib import convert_to_boolean
from bsql import Row
from collections.abc import Callable, Sequence
from dataclasses import Field, asdict, dataclass, fields
from typing import TYPE_CHECKING, Any

from .. import logger as logging

if TYPE_CHECKING:
	from typing import Self


THEMES = {
	'default': {
		'text': '#DDD',
		'background': '#222',
		'primary': '#D85',
		'primary-hover': '#DA8',
		'section-background': '#333',
		'table-background': '#444',
		'border': '#444',
		'message-text': '#DDD',
		'message-background': '#335',
		'message-border': '#446',
		'error-text': '#DDD',
		'error-background': '#533',
		'error-border': '#644'
	},
	'pink': {
		'text': '#DDD',
		'background': '#222',
		'primary': '#D69',
		'primary-hover': '#D36',
		'section-background': '#333',
		'table-background': '#444',
		'border': '#444',
		'message-text': '#DDD',
		'message-background': '#335',
		'message-border': '#446',
		'error-text': '#DDD',
		'error-background': '#533',
		'error-border': '#644'
	},
	'blue': {
		'text': '#DDD',
		'background': '#222',
		'primary': '#69D',
		'primary-hover': '#36D',
		'section-background': '#333',
		'table-background': '#444',
		'border': '#444',
		'message-text': '#DDD',
		'message-background': '#335',
		'message-border': '#446',
		'error-text': '#DDD',
		'error-background': '#533',
		'error-border': '#644'
	}
}

# serializer | deserializer
CONFIG_CONVERT: dict[str, tuple[Callable[[Any], str], Callable[[str], Any]]] = {
	'str': (str, str),
	'int': (str, int),
	'bool': (str, convert_to_boolean),
	'logging.LogLevel': (lambda x: x.name, logging.LogLevel.parse)
}


@dataclass()
class ConfigData:
	schema_version: int = 20240625
	private_key: str = ''
	approval_required: bool = False
	log_level: logging.LogLevel = logging.LogLevel.INFO
	name: str = 'ActivityRelay'
	note: str = ''
	theme: str = 'default'
	whitelist_enabled: bool = False


	def __getitem__(self, key: str) -> Any:
		if (value := getattr(self, key.replace('-', '_'), None)) is None:
			raise KeyError(key)

		return value


	def __setitem__(self, key: str, value: Any) -> None:
		self.set(key, value)


	@classmethod
	def KEYS(cls: type[Self]) -> Sequence[str]:
		return list(cls.__dataclass_fields__)


	@staticmethod
	def SYSTEM_KEYS() -> Sequence[str]:
		return ('schema-version', 'schema_version', 'private-key', 'private_key')


	@classmethod
	def USER_KEYS(cls: type[Self]) -> Sequence[str]:
		return tuple(key for key in cls.KEYS() if key not in cls.SYSTEM_KEYS())


	@classmethod
	def DEFAULT(cls: type[Self], key: str) -> str | int | bool:
		return cls.FIELD(key.replace('-', '_')).default # type: ignore[return-value]


	@classmethod
	def FIELD(cls: type[Self], key: str) -> Field[str | int | bool]:
		for field in fields(cls):
			if field.name == key.replace('-', '_'):
				return field

		raise KeyError(key)


	@classmethod
	def from_rows(cls: type[Self], rows: Sequence[Row]) -> Self:
		data = cls()
		set_schema_version = False

		for row in rows:
			data.set(row['key'], row['value'])

			if row['key'] == 'schema-version':
				set_schema_version = True

		if not set_schema_version:
			data.schema_version = 0

		return data


	def get(self, key: str, default: Any = None, serialize: bool = False) -> Any:
		field = type(self).FIELD(key)
		value = getattr(self, field.name, None)

		if not serialize:
			return value

		converter = CONFIG_CONVERT[str(field.type)][0]
		return converter(value)


	def set(self, key: str, value: Any) -> None:
		field = type(self).FIELD(key)
		converter = CONFIG_CONVERT[str(field.type)][1]

		setattr(self, field.name, converter(value))


	def to_dict(self) -> dict[str, Any]:
		return {key.replace('_', '-'): value for key, value in asdict(self).items()}
