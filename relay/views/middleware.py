import traceback

from Crypto.Random import get_random_bytes
from aiohttp.web import HTTPException, Request, StreamResponse, middleware
from base64 import b64encode
from blib import HttpError
from collections.abc import Awaitable, Callable

from ..misc import JSON_PATHS, TOKEN_PATHS, Response, get_state
from ..state import State


def get_csp(state: State, request: Request) -> str:
	data = [
		"default-src 'self'",
		f"script-src 'nonce-{request['hash']}'",
		f"style-src 'self' 'nonce-{request['hash']}'",
		"form-action 'self'",
		"connect-src 'self'",
		"img-src 'self'",
		"object-src 'none'",
		"frame-ancestors 'none'",
		f"manifest-src 'self' https://{state.config.domain}"
	]

	return "; ".join(data) + ";"


def format_error(request: Request, error: HttpError) -> Response:
	if request.path.startswith(JSON_PATHS) or "json" in request.headers.get("accept", ""):
		return Response.new({"error": error.message}, error.status, ctype = "json")

	else:
		context = {"e": error}
		return Response.new_template(error.status, "page/error.haml", request, context)


@middleware
async def handle_response_headers(
						request: Request,
						handler: Callable[[Request], Awaitable[StreamResponse]]) -> StreamResponse:

	request["hash"] = b64encode(get_random_bytes(16)).decode("ascii")
	request["token"] = None
	request["user"] = None

	state = get_state()

	if request.path in {"/", "/docs"} or request.path.startswith(TOKEN_PATHS):
		with state.database.session() as conn:
			tokens = (
				request.headers.get("Authorization", "").replace("Bearer", "").strip(),
				request.cookies.get("user-token")
			)

			for token in tokens:
				if not token:
					continue

				request["token"] = conn.get_app_by_token(token)

				if request["token"] is not None:
					request["user"] = conn.get_user(request["token"].user)

				break

	try:
		resp = await handler(request)

	except HttpError as e:
		resp = format_error(request, e)

	except HTTPException as e:
		if e.status == 404:
			try:
				text = (e.text or "").split(":")[1].strip()

			except IndexError:
				text = e.text or ""

			resp = format_error(request, HttpError(e.status, text))

		else:
			raise

	except Exception:
		resp = format_error(request, HttpError(500, "Internal server error"))
		traceback.print_exc()

	resp.headers["Server"] = "ActivityRelay"

	# Still have to figure out how csp headers work
	if resp.content_type == "text/html" and not request.path.startswith("/api"):
		resp.headers["Content-Security-Policy"] = get_csp(state, request)

	if not state.dev and request.path.endswith((".css", ".js", ".woff2")):
		# cache for 2 weeks
		resp.headers["Cache-Control"] = "public,max-age=1209600,immutable"

	else:
		resp.headers["Cache-Control"] = "no-store"

	return resp


@middleware
async def handle_frontend_path(
						request: Request,
						handler: Callable[[Request], Awaitable[StreamResponse]]) -> StreamResponse:

	if request["user"] is not None and request.path == "/login":
		return Response.new_redir("/")

	if request.path.startswith(TOKEN_PATHS[:2]) and request["user"] is None:
		if request.path == "/logout":
			return Response.new_redir("/")

		response: StreamResponse = Response.new_redir(f"/login?redir={request.path}")

		if request["token"] is not None:
			response.del_cookie("user-token")

		return response

	response = await handler(request)

	if not request.path.startswith("/api"):
		if request["user"] is None and request["token"] is not None:
			response.del_cookie("user-token")

	return response
