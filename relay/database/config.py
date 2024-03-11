from __future__ import annotations

import json
import typing

from .. import logger as logging
from ..misc import boolean

if typing.TYPE_CHECKING:
	from collections.abc import Callable
	from typing import Any


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

CONFIG_DEFAULTS: dict[str, tuple[str, Any]] = {
	'schema-version': ('int', 20240310),
	'private-key': ('str', None),
	'approval-required': ('bool', False),
	'log-level': ('loglevel', logging.LogLevel.INFO),
	'name': ('str', 'ActivityRelay'),
	'note': ('str', 'Make a note about your instance here.'),
	'theme': ('str', 'default'),
	'whitelist-enabled': ('bool', False)
}

# serializer | deserializer
CONFIG_CONVERT: dict[str, tuple[Callable, Callable]] = {
	'str': (str, str),
	'int': (str, int),
	'bool': (str, boolean),
	'json': (json.dumps, json.loads),
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
