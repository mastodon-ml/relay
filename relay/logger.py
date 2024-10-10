from __future__ import annotations

import logging
import os

from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
	from typing import Self


class LoggingMethod(Protocol):
	def __call__(self, msg: Any, *args: Any, **kwargs: Any) -> None: ...


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
	def parse(cls: type[Self], data: Any) -> Self:
		try:
			data = int(data)

		except ValueError:
			pass

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
	if not logging.root.isEnabledFor(LogLevel.VERBOSE):
		return

	logging.log(LogLevel.VERBOSE, message, *args, **kwargs)


debug: LoggingMethod = logging.debug
info: LoggingMethod = logging.info
warning: LoggingMethod = logging.warning
error: LoggingMethod = logging.error
critical: LoggingMethod = logging.critical


try:
	env_log_file: Path | None = Path(os.environ['LOG_FILE']).expanduser().resolve()

except KeyError:
	env_log_file = None

handlers: list[Any] = [logging.StreamHandler()]

if env_log_file:
	handlers.append(logging.FileHandler(env_log_file))

if os.environ.get('IS_SYSTEMD'):
	logging_format = '%(levelname)s: %(message)s'

else:
	logging_format = '[%(asctime)s] %(levelname)s: %(message)s'

logging.addLevelName(LogLevel.VERBOSE, 'VERBOSE')
logging.basicConfig(
	level = LogLevel.INFO,
	format = logging_format,
	datefmt = '%Y-%m-%d %H:%M:%S',
	handlers = handlers
)
