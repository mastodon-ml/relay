from __future__ import annotations

import traceback

from aiohttp.web import Request
from argon2.exceptions import VerifyMismatchError
from blib import HttpError, HttpMethod, convert_to_boolean
from typing import Any
from urllib.parse import urlparse

from .base import DEFAULT_REDIRECT, Route

from .. import api_objects as objects, __version__
from ..database import ConfigData, schema
from ..misc import Message, Response, idna_to_utf
from ..state import State


@Route(HttpMethod.GET, "/oauth/authorize", "Authorization", False)
async def handle_authorize_get(
			state: State,
			request: Request,
			response_type: str,
			client_id: str,
			redirect_uri: str) -> Response:
	"""
		Authorize an application.

		Redirects to the application's redirect URI if accepted.

		:param response_type: What to respond with. Should always be set to ``code``.
		:param client_id: Application identifier
		:param redirect_uri: URI to redirect to on accept
	"""

	if response_type != "code":
		raise HttpError(400, "Response type is not 'code'")

	with state.database.session(True) as s:
		with s.select("apps", client_id = client_id) as cur:
			if (application := cur.one(schema.App)) is None:
				raise HttpError(404, "Could not find app")

	if application.token is not None:
		raise HttpError(400, "Application has already been authorized")

	if application.auth_code is not None:
		page = "page/authorization_show.haml"

	else:
		page = "page/authorize_new.haml"

		if redirect_uri != application.redirect_uri:
			raise HttpError(400, "redirect_uri does not match application")

	context = {"application": application}
	return Response.new_template(200, page, request, context)


@Route(HttpMethod.POST, "/oauth/authorize", "Authorization", False)
async def handle_authorize_post(
			state: State,
			request: Request,
			client_id: str,
			client_secret: str,
			redirect_uri: str,
			response: str) -> Response:

	with state.database.session(True) as s:
		if (application := s.get_app(client_id, client_secret)) is None:
			raise HttpError(404, "Could not find app")

		if convert_to_boolean(response):
			if application.token is not None:
				raise HttpError(400, "Application has already been authorized")

			if application.auth_code is None:
				application = s.update_app(application, request["user"], True)

			if application.redirect_uri == DEFAULT_REDIRECT:
				context = {"application": application}
				return Response.new_template(200, "page/authorize_show.haml", request, context)

			return Response.new_redir(f"{application.redirect_uri}?code={application.auth_code}")

		if not s.del_app(application.client_id, application.client_secret):
			raise HttpError(404, "App not found")

		return Response.new_redir("/")


@Route(HttpMethod.POST, "/oauth/token", "Authorization", False)
async def handle_new_token(
						state: State,
						request: Request,
						grant_type: str,
						code: str,
						client_id: str,
						client_secret: str,
						redirect_uri: str) -> objects.Application:
	"""
		Get a new access token for an application

		:param grant_type: Access level for the application. Should be ``authorization_code``
		:param code: Authorization code obtained from ``/oauth/authorize``
		:param client_id: The application to create the token for
		:param client_secret: Secret of the specified application
		:param redirect_uri: URI to redirect to
	"""

	if grant_type != "authorization_code":
		raise HttpError(400, "Invalid grant type")

	with state.database.session(True) as s:
		if (application := s.get_app(client_id, client_secret)) is None:
			raise HttpError(404, "Application not found")

		if application.auth_code != code:
			raise HttpError(400, "Invalid authentication code")

		if application.redirect_uri != redirect_uri:
			raise HttpError(400, "Invalid redirect uri")

		application = s.update_app(application, request["user"], False)

	return objects.Application.from_row(application)


@Route(HttpMethod.POST, "/api/oauth/revoke", "Authorization", True)
async def handle_token_revoke(
			state: State,
			request: Request,
			client_id: str,
			client_secret: str,
			token: str) -> objects.Message:
	"""
		Revoke and destroy a token

		:param client_id: Identifier of the application to revoke
		:param client_secret: Secret of the application
		:param token: Token associated with the application
	"""

	with state.database.session(True) as conn:
		if (application := conn.get_app(client_id, client_secret, token)) is None:
			raise HttpError(404, "Could not find token")

		if application.user != request["application"].username:
			raise HttpError(403, "Invalid token")

		if not conn.del_app(client_id, client_secret, token):
			raise HttpError(400, "Token not removed")

		return objects.Message("Token deleted")


@Route(HttpMethod.POST, "/api/v1/login", "Authorization", False)
async def handle_login(
					state: State,
					request: Request,
					username: str,
					password: str) -> objects.Application:
	"""
		Create a new token via username and password.

		It is recommended to use oauth instead.

		:param username: Name of the user to login
		:param password: Password of the user
	"""

	with state.database.session(True) as s:
		if not (user := s.get_user(username)):
			raise HttpError(401, "User not found")

		try:
			s.hasher.verify(user.hash, password)

		except VerifyMismatchError:
			raise HttpError(401, "Invalid password")

		application = s.put_app_login(user)

	return objects.Application(
		application.client_id,
		application.client_secret,
		application.name,
		application.website,
		application.redirect_uri,
		application.token,
		application.created,
		application.accessed
	)


@Route(HttpMethod.GET, "/api/v1/app", "Application", True)
async def handle_get_app(state: State, request: Request) -> objects.Application:
	"Get data for the application currently in use"

	return objects.Application.from_row(request["application"])


@Route(HttpMethod.POST, "/api/v1/app", "Application", True)
async def handle_create_app(
							state: State,
							request: Request,
							name: str,
							redirect_uri: str,
							website: str | None = None) -> objects.Application:
	"""
		Create a new application

		:param name: User-readable name of the application
		:param redirect_uri: URI to redirect to on authorization
		:param website: Homepage of the application
	"""

	with state.database.session(True) as conn:
		application = conn.put_app(
			name = name,
			redirect_uri = redirect_uri,
			website = website
		)

	return objects.Application.from_row(application)


@Route(HttpMethod.GET, "/api/v1/config", "Config", True)
async def handle_config_get(state: State, request: Request) -> objects.Config:
	"Get all config options"

	with state.database.session(False) as conn:
		return objects.Config.from_config(conn.get_config_all())


@Route(HttpMethod.GET, "/api/v2/config", "Config", True)
async def handle_config_get_v2(state: State, request: Request) -> list[objects.ConfigItem]:
	"Get all config options including the type name for each"

	data: list[objects.ConfigItem] = []
	cfg = ConfigData()
	user_keys = ConfigData.USER_KEYS()

	with state.database.session(False) as s:
		for row in s.execute("SELECT * FROM \"config\"").all(schema.Config):
			if row.key.replace("-", "_") not in user_keys:
				continue

			cfg.set(row.key, row.value)
			data.append(objects.ConfigItem(row.key, cfg.get(row.key), row.type))

	return data


@Route(HttpMethod.POST, "/api/v1/config", "Config", True)
async def handle_config_update(
							state: State,
							request: Request,
							key: str,
							value: Any) -> objects.Message:
	"""
		Set a value for a config option

		:param key: Name of the config option to set
		:param value: New value
	"""

	if (field := ConfigData.FIELD(key)).name not in ConfigData.USER_KEYS():
		raise HttpError(400, "Invalid key")

	with state.database.session() as conn:
		value = conn.put_config(key, value)

	if field.name == "log_level":
		state.workers.set_log_level(value)

	return objects.Message("Updated config")


@Route(HttpMethod.DELETE, "/api/v1/config", "Config", True)
async def handle_config_reset(state: State, request: Request, key: str) -> objects.Message:
	"""
		Set a config option to the default value

		:param key: Name of the config option to reset
	"""

	if (field := ConfigData.FIELD(key)).name not in ConfigData.USER_KEYS():
		raise HttpError(400, "Invalid key")

	with state.database.session() as conn:
		value = conn.put_config(field.name, field.default)

	if field.name == "log_level":
		state.workers.set_log_level(value)

	return objects.Message("Updated config")


@Route(HttpMethod.GET, "/api/v1/relay", "Misc", False)
async def get(state: State, request: Request) -> objects.Relay:
	"Get info about the relay instance"

	with state.database.session() as s:
		config = s.get_config_all()
		inboxes = [row.domain for row in s.get_inboxes()]

	return objects.Relay(
		state.config.domain,
		config.name,
		config.note,
		__version__,
		config.whitelist_enabled,
		None,
		None,
		None,
		inboxes
	)


@Route(HttpMethod.GET, "/api/v1/instance", "Instance", True)
async def handle_instances_get(state: State, request: Request) -> list[objects.Instance]:
	"Get all subscribed instances"

	data: list[objects.Instance] = []

	with state.database.session(False) as s:
		for row in s.get_inboxes():
			data.append(objects.Instance.from_row(row))

	return data


@Route(HttpMethod.POST, "/api/v1/instance", "Instance", True)
async def handle_instance_add(
			state: State,
			request: Request,
			actor: str,
			inbox: str | None = None,
			software: str | None = None,
			followid: str | None = None) -> objects.Instance:
	"""
		Add an instance to the database

		:param actor: URL of the instance actor to add. Usually ``https://{domain}/actor``.
		:param inbox: URL of the inbox for the instance actor
		:param software: Name of the server software as displayed in nodeinfo
		:param followid: URL to the ``Follow`` activity
	"""

	domain = idna_to_utf(urlparse(actor).netloc)

	with state.database.session(False) as s:
		if s.get_inbox(domain) is not None:
			raise HttpError(404, "Instance already in database")

		if inbox is None:
			try:
				actor_data = await state.client.get(actor, True, Message)

			except Exception:
				traceback.print_exc()
				raise HttpError(500, "Failed to fetch actor") from None

			inbox = actor_data.shared_inbox

		if software is None:
			try:
				software = (await state.client.fetch_nodeinfo(domain)).sw_name

			except Exception:
				traceback.print_exc()

		row = s.put_inbox(
			domain = domain,
			actor = idna_to_utf(actor),
			inbox = idna_to_utf(inbox),
			software = idna_to_utf(software),
			followid = idna_to_utf(followid)
		)

	return objects.Instance.from_row(row)


@Route(HttpMethod.PATCH, "/api/v1/instance", "Instance", True)
async def handle_instance_update(
			state: State,
			request: Request,
			domain: str,
			actor: str | None = None,
			inbox: str | None = None,
			software: str | None = None,
			followid: str | None = None) -> objects.Instance:
	"""
		Update info for an instance

		:param domain: Hostname of the instance to modify
		:param actor: URL of the instance actor to add. Usually ``https://{domain}/actor``.
		:param inbox: URL of the inbox for the instance actor
		:param software: Name of the server software as displayed in nodeinfo
		:param followid: URL to the ``Follow`` activity
	"""

	domain = idna_to_utf(domain)

	with state.database.session(False) as s:
		if (instance := s.get_inbox(domain)) is None:
			raise HttpError(404, "Instance with domain not found")

		row = s.put_inbox(
			instance.domain,
			actor = idna_to_utf(actor) or instance.actor,
			inbox = idna_to_utf(inbox) or instance.inbox,
			software = idna_to_utf(software) or instance.software,
			followid = idna_to_utf(followid) or instance.followid
		)

	return objects.Instance.from_row(row)


@Route(HttpMethod.DELETE, "/api/v1/instance", "Instance", True)
async def handle_instance_del(state: State, request: Request, domain: str) -> objects.Message:
	"""
		Remove an instance from the database

		:param domain: Hostname of the instance to remove
	"""

	domain = idna_to_utf(domain)

	with state.database.session(False) as s:
		if not s.get_inbox(domain):
			raise HttpError(404, "Instance with domain not found")

		s.del_inbox(domain)

	return objects.Message("Removed instance")


@Route(HttpMethod.GET, "/api/v1/request", "Request", True)
async def handle_requests_get(state: State, request: Request) -> list[objects.Instance]:
	"""
		Get all follow requests.

		This feature only works when ``Approval Required`` is enabled.
	"""

	data: list[objects.Instance] = []

	with state.database.session(False) as s:
		for row in s.get_requests():
			data.append(objects.Instance.from_row(row))

	return data


@Route(HttpMethod.POST, "/api/v1/request", "Request", True)
async def handle_request_response(
								state: State,
								request: Request,
								domain: str,
								accept: bool) -> objects.Message:
	"""
		Approve or reject a follow request

		:param domain: Hostname of the instance that requested to follow
		:param accept: Accept (``True``) or reject (``False``) the request
	"""

	try:
		with state.database.session(True) as conn:
			row = conn.put_request_response(domain, accept)

	except KeyError:
		raise HttpError(404, "Request not found") from None

	message = Message.new_response(
		host = state.config.domain,
		actor = row.actor,
		followid = row.followid,
		accept = accept
	)

	state.push_message(row.inbox, message, row)

	if accept and row.software != "mastodon":
		message = Message.new_follow(
			host = state.config.domain,
			actor = row.actor
		)

		state.push_message(row.inbox, message, row)

	if accept:
		return objects.Message("Request accepted")

	return objects.Message("Request denied")


@Route(HttpMethod.GET, "/api/v1/domain_ban", "Domain Ban", True)
async def handle_domain_bans_get(state: State, request: Request) -> list[objects.DomainBan]:
	"Get all banned domains"

	data: list[objects.DomainBan] = []

	with state.database.session(False) as s:
		for row in s.get_domain_bans():
			data.append(objects.DomainBan.from_row(row))

	return data


@Route(HttpMethod.POST, "/api/v1/domain_ban", "Domain Ban", True)
async def handle_domain_ban_add(
								state: State,
								request: Request,
								domain: str,
								note: str | None = None,
								reason: str | None = None) -> objects.DomainBan:
	"""
		Ban a domain.

		Banned domains cannot follow the relay. Posts originating from a banned instance will be
		ignored in a future update.

		:param domain: Hostname to ban
		:param note: Additional details about the ban that can only be viewed by admins
		:param reason: Publicly viewable details for the ban
	"""

	with state.database.session(False) as s:
		if s.get_domain_ban(domain) is not None:
			raise HttpError(400, "Domain already banned")

		row = s.put_domain_ban(domain, reason, note)
		return objects.DomainBan.from_row(row)


@Route(HttpMethod.PATCH, "/api/v1/domain_ban", "Domain Ban", True)
async def handle_domain_ban_update(
								state: State,
								request: Request,
								domain: str,
								note: str | None = None,
								reason: str | None = None) -> objects.DomainBan:
	"""
		Update a domain ban

		:param domain: Hostname to ban
		:param note: Additional details about the ban that can only be viewed by admins
		:param reason: Publicly viewable details for the ban
	"""

	with state.database.session(True) as s:
		if not any([note, reason]):
			raise HttpError(400, "Must include note and/or reason parameters")

		if s.get_domain_ban(domain) is None:
			raise HttpError(404, "Domain not banned")

		row = s.update_domain_ban(domain, reason, note)
		return objects.DomainBan.from_row(row)


@Route(HttpMethod.DELETE, "/api/v1/domain_ban", "Domain Ban", True)
async def handle_domain_unban(state: State, request: Request, domain: str) -> objects.Message:
	"""
		Unban a domain

		:param domain: Hostname to unban
	"""

	with state.database.session(True) as s:
		if s.get_domain_ban(domain) is None:
			raise HttpError(404, "Domain not banned")

		s.del_domain_ban(domain)

	return objects.Message("Unbanned domain")


@Route(HttpMethod.GET, "/api/v1/software_ban", "Software Ban", True)
async def handle_software_bans_get(state: State, request: Request) -> list[objects.SoftwareBan]:
	"Get all banned software"

	data: list[objects.SoftwareBan] = []

	with state.database.session(False) as s:
		for row in s.get_software_bans():
			data.append(objects.SoftwareBan.from_row(row))

	return data


@Route(HttpMethod.POST, "/api/v1/software_ban", "Software Ban", True)
async def handle_software_ban_add(
								state: State,
								request: Request,
								name: str,
								note: str | None = None,
								reason: str | None = None) -> objects.SoftwareBan:
	"""
		Ban all instanstances that use the specified software

		:param name: Nodeinfo name of the software to ban
		:param note: Additional details about the ban that can only be viewed by admins
		:param reason: Publicly viewable details for the ban
	"""

	with state.database.session(True) as s:
		if s.get_software_ban(name) is not None:
			raise HttpError(400, "Software already banned")

		row = s.put_software_ban(name, reason, note)
		return objects.SoftwareBan.from_row(row)


@Route(HttpMethod.PATCH, "/api/v1/software_ban", "Software Ban", True)
async def handle_software_ban(
							state: State,
							request: Request,
							name: str,
							note: str | None = None,
							reason: str | None = None) -> objects.SoftwareBan:
	"""
		Update a software ban

		:param name: Nodeinfo name of the software ban to modify
		:param note: Additional details about the ban that can only be viewed by admins
		:param reason: Publicly viewable details for the ban
	"""

	with state.database.session(True) as s:
		if not any([note, reason]):
			raise HttpError(400, "Must include note and/or reason parameters")

		if s.get_software_ban(name) is None:
			raise HttpError(404, "Software not banned")

		row = s.update_software_ban(name, reason, note)
		return objects.SoftwareBan.from_row(row)


@Route(HttpMethod.PATCH, "/api/v1/software_ban", "Software Ban", True)
async def handle_software_unban(state: State, request: Request, name: str) -> objects.Message:
	"""
		Unban the specified software

		:param name: Nodeinfo name of the software to unban
	"""

	with state.database.session(True) as s:
		if s.get_software_ban(name) is None:
			raise HttpError(404, "Software not banned")

		s.del_software_ban(name)

	return objects.Message("Unbanned software")


@Route(HttpMethod.GET, "/api/v1/whitelist", "Whitelist", True)
async def handle_whitelist_get(state: State, request: Request) -> list[objects.Whitelist]:
	"""
		Get all currently whitelisted domains
	"""

	data: list[objects.Whitelist] = []

	with state.database.session(False) as s:
		for row in s.get_domains_whitelist():
			data.append(objects.Whitelist.from_row(row))

	return data


@Route(HttpMethod.POST, "/api/v1/whitelist", "Whitelist", True)
async def handle_whitelist_add(
							state: State,
							request: Request,
							domain: str) -> objects.Whitelist:
	"""
		Add a domain to the whitelist

		:param domain: Hostname to allow
	"""

	with state.database.session(True) as s:
		if s.get_domain_whitelist(domain) is not None:
			raise HttpError(400, "Domain already added to whitelist")

		row = s.put_domain_whitelist(domain)
		return objects.Whitelist.from_row(row)


@Route(HttpMethod.DELETE, "/api/v1/whitelist", "Whitelist", True)
async def handle_whitelist_del(state: State, request: Request, domain: str) -> objects.Message:
	"""
		Remove a domain from the whitelist

		:param domain: Hostname to remove from the whitelist
	"""

	with state.database.session(True) as s:
		if s.get_domain_whitelist(domain) is None:
			raise HttpError(404, "Domain not in whitelist")

		s.del_domain_whitelist(domain)

	return objects.Message("Removed domain from whitelist")


# remove /api/v1/user endpoints in 0.4.0
@Route(HttpMethod.GET, "/api/v1/user", "User", True)
async def handle_users_get(state: State, request: Request) -> list[objects.User]:
	with state.database.session(False) as s:
		items = []

		for row in s.get_users():
			items.append(objects.User.from_row(row, "hash"))

	return items


@Route(HttpMethod.POST, "/api/v1/user", "User", True)
async def handle_user_add(
			state: State,
			request: Request,
			username: str,
			password: str,
			handle: str | None = None) -> objects.User:

	with state.database.session() as s:
		if s.get_user(username) is not None:
			raise HttpError(404, "User already exists")

		row = s.put_user(username, password, handle)
		return objects.User.from_row(row, "hash")


@Route(HttpMethod.PATCH, "/api/v1/user", "User", True)
async def handle_user_update(
			state: State,
			request: Request,
			username: str,
			password: str | None = None,
			handle: str | None = None) -> objects.User:

	with state.database.session(True) as s:
		if s.get_user(username) is None:
			raise HttpError(404, "User does not  exist")

		row = s.put_user(username, password, handle)
		return objects.User.from_row(row, "hash")


@Route(HttpMethod.DELETE, "/api/v1/user", "User", True)
async def handle_user_del(state: State, request: Request, username: str) -> objects.Message:
	with state.database.session(True) as s:
		if s.get_user(username) is None:
			raise HttpError(404, "User does not exist")

		s.del_user(username)

	return objects.Message("Deleted user")
