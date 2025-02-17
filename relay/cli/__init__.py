from __future__ import annotations

import click
import json
import multiprocessing

from blib import File
from collections.abc import Callable
from functools import update_wrapper
from typing import Concatenate, ParamSpec, TypeVar

from .. import __version__
from ..application import Application
from ..misc import IS_DOCKER


P = ParamSpec("P")
R = TypeVar("R")


@click.group("cli", context_settings = {"show_default": True})
@click.option("--config", "-c", type = File, help = "path to the relay config")
@click.version_option(version = __version__, prog_name = "ActivityRelay")
@click.pass_context
def cli(ctx: click.Context, config: File | None) -> None:
	if IS_DOCKER:
		config = File("/data/relay.yaml")

		# The database was named "relay.jsonld" even though it"s an sqlite file. Fix it.
		db = File("/data/relay.sqlite3")
		wrongdb = File("/data/relay.jsonld")

		if wrongdb.exists and not db.exists:
			try:
				with wrongdb.open("rb") as fd:
					json.load(fd)

			except json.JSONDecodeError:
				wrongdb.move(db)

	ctx.obj = Application(config)


def pass_app(func: Callable[Concatenate[Application, P], R]) -> Callable[P, R]:
	def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
		return func(Application.default(), *args, **kwargs)

	return update_wrapper(wrapper, func)


def main() -> None:
	multiprocessing.freeze_support()
	cli(prog_name="activityrelay")


from . import ( # noqa: E402
	base,
	config as config_cli,
	inbox,
	instance_ban,
	request,
	software_ban,
	user,
	whitelist
)
