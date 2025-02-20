from __future__ import annotations

import asyncio
import click
import inspect
import json
import multiprocessing

from blib import File
from collections.abc import Callable
from functools import update_wrapper
from typing import Concatenate, ParamSpec, TypeVar

from .. import __version__
from ..misc import IS_DOCKER
from ..state import State


try:
	import uvloop
	asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

except ImportError:
	pass


P = ParamSpec("P")
R = TypeVar("R")


@click.group("cli", context_settings = {"show_default": True})
@click.option("--config", "-c", type = File, help = "path to the relay config")
@click.version_option(version = __version__, prog_name = "ActivityRelay")
def cli(config: File | None) -> None:
	if IS_DOCKER:
		config = File("/data/relay.yaml")

		# The database was named "relay.jsonld" even though it's an sqlite file. Fix it.
		db = File("/data/relay.sqlite3")
		wrongdb = File("/data/relay.jsonld")

		if wrongdb.exists and not db.exists:
			try:
				with wrongdb.open("rb") as fd:
					json.load(fd)

			except json.JSONDecodeError:
				wrongdb.move(db)

	State(config, True)


def pass_state(func: Callable[Concatenate[State, P], R]) -> Callable[P, R]:
	def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
		if inspect.iscoroutinefunction(func):
			return asyncio.run(func(State.default(), *args, **kwargs)) # type: ignore[no-any-return]

		return func(State.default(), *args, **kwargs)

	return update_wrapper(wrapper, func)


def main() -> None:
	multiprocessing.freeze_support()
	cli(prog_name="activityrelay")


from . import ( # noqa: E402
	ban,
	base,
	config as config_cli,
	inbox,
	instance_ban,
	request,
	software_ban,
	user,
	whitelist
)
