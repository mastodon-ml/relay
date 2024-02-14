from __future__ import annotations

import typing

from .. import logger as logging
from ..misc import boolean

if typing.TYPE_CHECKING:
	from collections.abc import Callable
	from typing import Any


CONFIG_DEFAULTS: dict[str, tuple[str, Any]] = {
	'schema-version': ('int', 20240206),
	'log-level': ('loglevel', logging.LogLevel.INFO),
	'name': ('str', 'ActivityRelay'),
	'note': ('str', 'Make a note about your instance here.'),
	'private-key': ('str', None),
	'whitelist-enabled': ('bool', False)
}

# serializer | deserializer
CONFIG_CONVERT: dict[str, tuple[Callable, Callable]] = {
	'str': (str, str),
	'int': (str, int),
	'bool': (str, boolean),
	'loglevel': (lambda x: x.name, logging.LogLevel.parse)
}


def get_default_value(key: str) -> Any:
	return CONFIG_DEFAULTS[key][1]


def get_default_type(key: str) -> str:
	return CONFIG_DEFAULTS[key][0]


def serialize(key: str, value: Any) -> str:
	type_name = get_default_type(key)
	return CONFIG_CONVERT[type_name][0](value)


def deserialize(key: str, value: str) -> Any:
	type_name = get_default_type(key)
	return CONFIG_CONVERT[type_name][1](value)
