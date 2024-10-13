from __future__ import annotations

from blib import Date, JsonBase
from bsql import Row
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from . import logger as logging
from .database import ConfigData
from .misc import utf_to_idna

if TYPE_CHECKING:
	try:
		from typing import Self

	except ImportError:
		from typing_extensions import Self


class ApiObject:
	def __str__(self) -> str:
		return self.to_json()


	@classmethod
	def from_row(cls: type[Self], row: Row, *exclude: str) -> Self:
		return cls(**{k: v for k, v in row.items() if k not in exclude})


	def to_dict(self, *exclude: str) -> dict[str, Any]:
		return {k: v for k, v in asdict(self).items() if k not in exclude} # type: ignore[call-overload]


	def to_json(self, *exclude: str, indent: int | str | None = None) -> str:
		data = self.to_dict(*exclude)
		return JsonBase(data).to_json(indent = indent)


@dataclass(slots = True)
class Message(ApiObject):
	msg: str


@dataclass(slots = True)
class Application(ApiObject):
	client_id: str
	client_secret: str
	name: str
	website: str | None
	redirect_uri: str
	token: str | None
	created: Date
	updated: Date


@dataclass(slots = True)
class Config(ApiObject):
	approval_required: bool
	log_level: logging.LogLevel
	name: str
	note: str
	theme: str
	whitelist_enabled: bool


	@classmethod
	def from_config(cls: type[Self], cfg: ConfigData) -> Self:
		return cls(
			cfg.approval_required,
			cfg.log_level,
			cfg.name,
			cfg.note,
			cfg.theme,
			cfg.whitelist_enabled
		)


@dataclass(slots = True)
class ConfigItem(ApiObject):
	key: str
	value: Any
	type: str


@dataclass(slots = True)
class DomainBan(ApiObject):
	domain: str
	reason: str | None
	note: str | None
	created: Date


@dataclass(slots = True)
class Instance(ApiObject):
	domain: str
	actor: str
	inbox: str
	followid: str
	software: str
	accepted: Date
	created: Date


	def __post_init__(self) -> None:
		self.domain = utf_to_idna(self.domain)
		self.actor = utf_to_idna(self.actor)
		self.inbox = utf_to_idna(self.inbox)
		self.followid = utf_to_idna(self.followid)


@dataclass(slots = True)
class Relay(ApiObject):
	domain: str
	name: str
	description: str
	version: str
	whitelist_enabled: bool
	email: str | None
	admin: str | None
	icon: str | None
	instances: list[str]


@dataclass(slots = True)
class SoftwareBan(ApiObject):
	name: str
	reason: str | None
	note: str | None
	created: Date


@dataclass(slots = True)
class User(ApiObject):
	username: str
	handle: str | None
	created: Date


@dataclass(slots = True)
class Whitelist(ApiObject):
	domain: str
	created: Date
