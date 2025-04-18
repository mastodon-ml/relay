from __future__ import annotations

import aputils
import subprocess

from aiohttp.web import Request
from blib import File, HttpMethod
from typing import TYPE_CHECKING

from .base import register_route

from .. import __version__
from ..misc import Response

if TYPE_CHECKING:
	from ..application import Application


VERSION = __version__


if File(__file__).join("../../../.git").resolve().exists:
	try:
		commit_label = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode("ascii")
		VERSION = f"{__version__} {commit_label}"

		del commit_label

	except Exception:
		pass


NODEINFO_PATHS = [
	"/nodeinfo/{niversion:\\d.\\d}.json",
	"/nodeinfo/{niversion:\\d.\\d}"
]


@register_route(HttpMethod.GET, *NODEINFO_PATHS) # type: ignore[arg-type]
async def handle_nodeinfo(app: Application, request: Request, niversion: str) -> Response:
	with app.database.session() as conn:
		inboxes = conn.get_inboxes()

		nodeinfo = aputils.Nodeinfo.new(
			name = "activityrelay",
			version = VERSION,
			protocols = ["activitypub"],
			open_regs = not conn.get_config("whitelist-enabled"),
			users = 1,
			repo = "https://git.pleroma.social/pleroma/relay" if niversion == "2.1" else None,
			metadata = {
				"approval_required": conn.get_config("approval-required"),
				"peers": [inbox["domain"] for inbox in inboxes]
			}
		)

	return Response.new(nodeinfo, ctype = "json")


@register_route(HttpMethod.GET, "/.well-known/nodeinfo")
async def handle_wk_nodeinfo(app: Application, request: Request) -> Response:
	data = aputils.WellKnownNodeinfo.new_template(app.config.domain)

	return Response.new(data, ctype = "json")
