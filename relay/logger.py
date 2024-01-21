from __future__ import annotations

import logging
import os
import typing

from enum import IntEnum
from pathlib import Path

if typing.TYPE_CHECKING:
	from typing import Any, Callable, Type


class LogLevel(IntEnum):
	DEBUG = logging.DEBUG
	VERBOSE = 15
	INFO = logging.INFO
	WARNING = logging.WARNING
	ERROR = logging.ERROR
	CRITICAL = logging.CRITICAL


	def __str__(self) -> str:
		return self.name


	@classmethod
	def parse(cls: Type[IntEnum], data: object) -> IntEnum:
		if isinstance(data, cls):
			return data

		if isinstance(data, str):
			data = data.upper()

		try:
			return cls[data]

		except KeyError:
			pass

		try:
			return cls(data)

		except ValueError:
			pass

		raise AttributeError(f'Invalid enum property for {cls.__name__}: {data}')


def get_level() -> LogLevel:
	return LogLevel.parse(logging.root.level)


def set_level(level: LogLevel | str) -> None:
	logging.root.setLevel(LogLevel.parse(level))


def verbose(message: str, *args: Any, **kwargs: Any) -> None:
	if not logging.root.isEnabledFor(LogLevel['VERBOSE']):
		return

	logging.log(LogLevel['VERBOSE'], message, *args, **kwargs)


debug: Callable = logging.debug
info: Callable = logging.info
warning: Callable = logging.warning
error: Callable = logging.error
critical: Callable = logging.critical


logging.addLevelName(LogLevel['VERBOSE'], 'VERBOSE')
env_log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()

try:
	env_log_file = Path(os.environ['LOG_FILE']).expanduser().resolve()

except KeyError:
	env_log_file = None


try:
	log_level = LogLevel[env_log_level]

except KeyError:
	print('Invalid log level:', env_log_level)
	log_level = LogLevel['INFO']


handlers = [logging.StreamHandler()]

if env_log_file:
	handlers.append(logging.FileHandler(env_log_file))

logging.basicConfig(
	level = log_level,
	format = '[%(asctime)s] %(levelname)s: %(message)s',
	handlers = handlers
)
