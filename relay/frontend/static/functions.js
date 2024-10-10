// toast notifications

const notifications = document.querySelector("#notifications")


function remove_toast(toast) {
	toast.classList.add("hide");

	if (toast.timeoutId) {
		clearTimeout(toast.timeoutId);
	}

	setTimeout(() => toast.remove(), 300);
}

function toast(text, type="error", timeout=5) {
	const toast = document.createElement("li");
	toast.className = `section ${type}`
	toast.innerHTML = `<span class=".text">${text}</span><a href="#">&#10006;</span>`

	toast.querySelector("a").addEventListener("click", async (event) => {
		event.preventDefault();
		await remove_toast(toast);
	});

	notifications.appendChild(toast);
	toast.timeoutId = setTimeout(() => remove_toast(toast), timeout * 1000);
}


// menu

const body = document.getElementById("container")
const menu = document.getElementById("menu");
const menu_open = document.querySelector("#menu-open i");
const menu_close = document.getElementById("menu-close");


function toggle_menu() {
	let new_value = menu.attributes.visible.nodeValue === "true" ? "false" : "true";
	menu.attributes.visible.nodeValue = new_value;
}


menu_open.addEventListener("click", toggle_menu);
menu_close.addEventListener("click", toggle_menu);

body.addEventListener("click", (event) => {
	if (event.target === menu_open) {
		return;
	}

	menu.attributes.visible.nodeValue = "false";
});

for (const elem of document.querySelectorAll("#menu-open div")) {
	elem.addEventListener("click", toggle_menu);
}


// misc

function get_date_string(date) {
	var year = date.getUTCFullYear().toString();
	var month = (date.getUTCMonth() + 1).toString().padStart(2, "0");
	var day = date.getUTCDate().toString().padStart(2, "0");

	return `${year}-${month}-${day}`;
}


function append_table_row(table, row_name, row) {
	var table_row = table.insertRow(-1);
	table_row.id = row_name;

	index = 0;

	for (var prop in row) {
		if (Object.prototype.hasOwnProperty.call(row, prop)) {
			var cell = table_row.insertCell(index);
			cell.className = prop;
			cell.innerHTML = row[prop];

			index += 1;
		}
	}

	return table_row;
}


async function request(method, path, body = null) {
	var headers = {
		"Accept": "application/json"
	}

	if (body !== null) {
		headers["Content-Type"] = "application/json"
		body = JSON.stringify(body)
	}

	const response = await fetch("/api/" + path, {
		method: method,
		mode: "cors",
		cache: "no-store",
		redirect: "follow",
		body: body,
		headers: headers
	});

	const message = await response.json();

	if (Object.hasOwn(message, "error")) {
		throw new Error(message.error);
	}

	if (Array.isArray(message)) {
		message.forEach((msg) => {
			if (Object.hasOwn(msg, "created")) {
				msg.created = new Date(msg.created);
			}
		});

	} else {
		if (Object.hasOwn(message, "created")) {
			message.created = new Date(message.created);
		}
	}

	return message;
}

// page functions

function page_config() {
	const elems = [
		document.querySelector("#name"),
		document.querySelector("#note"),
		document.querySelector("#theme"),
		document.querySelector("#log-level"),
		document.querySelector("#whitelist-enabled"),
		document.querySelector("#approval-required")
	]


	async function handle_config_change(event) {
		params = {
			key: event.target.id,
			value: event.target.type === "checkbox" ? event.target.checked : event.target.value
		}

		try {
			await request("POST", "v1/config", params);

		} catch (error) {
			toast(error);
			return;
		}

		if (params.key === "name") {
			document.querySelector("#header .title").innerHTML = params.value;
			document.querySelector("title").innerHTML = params.value;
		}

		if (params.key === "theme") {
			document.querySelector("link.theme").href = `/theme/${params.value}.css`;
		}

		toast("Updated config", "message");
	}


	document.querySelector("#name").addEventListener("keydown", async (event) => {
		if (event.which === 13) {
			await handle_config_change(event);
		}
	});

	document.querySelector("#note").addEventListener("keydown", async (event) => {
		if (event.which === 13 && event.ctrlKey) {
			await handle_config_change(event);
		}
	});

	for (const elem of elems) {
		elem.addEventListener("change", handle_config_change);
	}
}


function page_domain_ban() {
	function create_ban_object(domain, reason, note) {
		var text = '<details>\n';
		text += `<summary>${domain}</summary>\n`;
		text += '<div class="grid-2col">\n';
		text += `<label for="${domain}-reason" class="reason">Reason</label>\n`;
		text += `<textarea id="${domain}-reason" class="reason">${reason}</textarea>\n`;
		text += `<label for="${domain}-note" class="note">Note</label>\n`;
		text += `<textarea id="${domain}-note" class="note">${note}</textarea>\n`;
		text += `<input class="update-ban" type="button" value="Update">`;
		text += '</details>';

		return text;
	}


	function add_row_listeners(row) {
		row.querySelector(".update-ban").addEventListener("click", async (event) => {
			await update_ban(row.id);
		});

		row.querySelector(".remove a").addEventListener("click", async (event) => {
			event.preventDefault();
			await unban(row.id);
		});
	}


	async function ban() {
		var table = document.querySelector("table");
		var elems = {
			domain: document.getElementById("new-domain"),
			reason: document.getElementById("new-reason"),
			note: document.getElementById("new-note")
		}

		var values = {
			domain: elems.domain.value.trim(),
			reason: elems.reason.value.trim(),
			note: elems.note.value.trim()
		}

		if (values.domain === "") {
			toast("Domain is required");
			return;
		}

		try {
			var ban = await request("POST", "v1/domain_ban", values);

		} catch (err) {
			toast(err);
			return
		}

		var row = append_table_row(document.querySelector("table"), ban.domain, {
			domain: create_ban_object(ban.domain, ban.reason, ban.note),
			date: get_date_string(ban.created),
			remove: `<a href="#" title="Unban domain">&#10006;</a>`
		});

		add_row_listeners(row);

		elems.domain.value = null;
		elems.reason.value = null;
		elems.note.value = null;

		document.querySelector("details.section").open = false;
		toast("Banned domain", "message");
	}


	async function update_ban(domain) {
		var row = document.getElementById(domain);

		var elems = {
			"reason": row.querySelector("textarea.reason"),
			"note": row.querySelector("textarea.note")
		}

		var values = {
			"domain": domain,
			"reason": elems.reason.value,
			"note": elems.note.value
		}

		try {
			await request("PATCH", "v1/domain_ban", values)

		} catch (error) {
			toast(error);
			return;
		}

		row.querySelector("details").open = false;
		toast("Updated baned domain", "message");
	}


	async function unban(domain) {
		try {
			await request("DELETE", "v1/domain_ban", {"domain": domain});

		} catch (error) {
			toast(error);
			return;
		}

		document.getElementById(domain).remove();
		toast("Unbanned domain", "message");
	}


	document.querySelector("#new-ban").addEventListener("click", async (event) => {
		await ban();
	});

	for (var elem of document.querySelectorAll("#add-item input")) {
		elem.addEventListener("keydown", async (event) => {
			if (event.which === 13) {
				await ban();
			}
		});
	}

	for (var row of document.querySelector("fieldset.section table").rows) {
		if (!row.querySelector(".update-ban")) {
			continue;
		}

		add_row_listeners(row);
	}
}


function page_instance() {
	function add_instance_listeners(row) {
		row.querySelector(".remove a").addEventListener("click", async (event) => {
			event.preventDefault();
			await del_instance(row.id);
		});
	}


	function add_request_listeners(row) {
		row.querySelector(".approve a").addEventListener("click", async (event) => {
			event.preventDefault();
			await req_response(row.id, true);
		});

		row.querySelector(".deny a").addEventListener("click", async (event) => {
			event.preventDefault();
			await req_response(row.id, false);
		});
	}


	async function add_instance() {
		var elems = {
			actor: document.getElementById("new-actor"),
			inbox: document.getElementById("new-inbox"),
			followid: document.getElementById("new-followid"),
			software: document.getElementById("new-software")
		}

		var values = {
			actor: elems.actor.value.trim(),
			inbox: elems.inbox.value.trim(),
			followid: elems.followid.value.trim(),
			software: elems.software.value.trim()
		}

		if (values.actor === "") {
			toast("Actor is required");
			return;
		}

		try {
			var instance = await request("POST", "v1/instance", values);

		} catch (err) {
			toast(err);
			return
		}

		row = append_table_row(document.getElementById("instances"), instance.domain, {
			domain: `<a href="https://${instance.domain}/" target="_new">${instance.domain}</a>`,
			software: instance.software,
			date: get_date_string(instance.created),
			remove: `<a href="#" title="Remove Instance">&#10006;</a>`
		});

		add_instance_listeners(row);

		elems.actor.value = null;
		elems.inbox.value = null;
		elems.followid.value = null;
		elems.software.value = null;

		document.querySelector("details.section").open = false;
		toast("Added instance", "message");
	}


	async function del_instance(domain) {
		try {
			await request("DELETE", "v1/instance", {"domain": domain});

		} catch (error) {
			toast(error);
			return;
		}

		document.getElementById(domain).remove();
	}


	async function req_response(domain, accept) {
		params = {
			"domain": domain,
			"accept": accept
		}

		try {
			await request("POST", "v1/request", params);

		} catch (error) {
			toast(error);
			return;
		}

		document.getElementById(domain).remove();

		if (document.getElementById("requests").rows.length < 2) {
			document.querySelector("fieldset.requests").remove()
		}

		if (!accept) {
			toast("Denied instance request", "message");
			return;
		}

		instances = await request("GET", `v1/instance`, null);
		instances.forEach((instance) => {
			if (instance.domain === domain) {
				row = append_table_row(document.getElementById("instances"), instance.domain, {
					domain: `<a href="https://${instance.domain}/" target="_new">${instance.domain}</a>`,
					software: instance.software,
					date: get_date_string(instance.created),
					remove: `<a href="#" title="Remove Instance">&#10006;</a>`
				});

				add_instance_listeners(row);
			}
		});

		toast("Accepted instance request", "message");
	}


	document.querySelector("#add-instance").addEventListener("click", async (event) => {
		await add_instance();
	})

	for (var elem of document.querySelectorAll("#add-item input")) {
		elem.addEventListener("keydown", async (event) => {
			if (event.which === 13) {
				await add_instance();
			}
		});
	}

	for (var row of document.querySelector("#instances").rows) {
		if (!row.querySelector(".remove a")) {
			continue;
		}

		add_instance_listeners(row);
	}

	if (document.querySelector("#requests")) {
		for (var row of document.querySelector("#requests").rows) {
			if (!row.querySelector(".approve a")) {
				continue;
			}

			add_request_listeners(row);
		}
	}
}


function page_login() {
	const fields = {
		username: document.querySelector("#username"),
		password: document.querySelector("#password"),
		redir: document.querySelector("#redir")
	};

	async function login(event) {
		const values = {
			username: fields.username.value.trim(),
			password: fields.password.value.trim(),
			redir: fields.redir.value.trim()
		}

		if (values.username === "" | values.password === "") {
			toast("Username and/or password field is blank");
			return;
		}

		try {
			await request("POST", "v1/login", values);

		} catch (error) {
			toast(error);
			return;
		}

		document.location = values.redir;
	}


	document.querySelector("#username").addEventListener("keydown", async (event) => {
		if (event.which === 13) {
			fields.password.focus();
			fields.password.select();
		}
	});

	document.querySelector("#password").addEventListener("keydown", async (event) => {
		if (event.which === 13) {
			await login(event);
		}
	});

	document.querySelector(".submit").addEventListener("click", login);
}


function page_software_ban() {
	function create_ban_object(name, reason, note) {
		var text = '<details>\n';
		text += `<summary>${name}</summary>\n`;
		text += '<div class="grid-2col">\n';
		text += `<label for="${name}-reason" class="reason">Reason</label>\n`;
		text += `<textarea id="${name}-reason" class="reason">${reason}</textarea>\n`;
		text += `<label for="${name}-note" class="note">Note</label>\n`;
		text += `<textarea id="${name}-note" class="note">${note}</textarea>\n`;
		text += `<input class="update-ban" type="button" value="Update">`;
		text += '</details>';

		return text;
	}


	function add_row_listeners(row) {
		row.querySelector(".update-ban").addEventListener("click", async (event) => {
			await update_ban(row.id);
		});

		row.querySelector(".remove a").addEventListener("click", async (event) => {
			event.preventDefault();
			await unban(row.id);
		});
	}


	async function ban() {
		var elems = {
			name: document.getElementById("new-name"),
			reason: document.getElementById("new-reason"),
			note: document.getElementById("new-note")
		}

		var values = {
			name: elems.name.value.trim(),
			reason: elems.reason.value,
			note: elems.note.value
		}

		if (values.name === "") {
			toast("Domain is required");
			return;
		}

		try {
			var ban = await request("POST", "v1/software_ban", values);

		} catch (err) {
			toast(err);
			return
		}

		var row = append_table_row(document.getElementById("bans"), ban.name, {
			name: create_ban_object(ban.name, ban.reason, ban.note),
			date: get_date_string(ban.created),
			remove: `<a href="#" title="Unban software">&#10006;</a>`
		});

		add_row_listeners(row);

		elems.name.value = null;
		elems.reason.value = null;
		elems.note.value = null;

		document.querySelector("details.section").open = false;
		toast("Banned software", "message");
	}


	async function update_ban(name) {
		var row = document.getElementById(name);

		var elems = {
			"reason": row.querySelector("textarea.reason"),
			"note": row.querySelector("textarea.note")
		}

		var values = {
			"name": name,
			"reason": elems.reason.value,
			"note": elems.note.value
		}

		try {
			await request("PATCH", "v1/software_ban", values)

		} catch (error) {
			toast(error);
			return;
		}

		row.querySelector("details").open = false;
		toast("Updated software ban", "message");
	}


	async function unban(name) {
		try {
			await request("DELETE", "v1/software_ban", {"name": name});

		} catch (error) {
			toast(error);
			return;
		}

		document.getElementById(name).remove();
		toast("Unbanned software", "message");
	}


	document.querySelector("#new-ban").addEventListener("click", async (event) => {
		await ban();
	});

	for (var elem of document.querySelectorAll("#add-item input")) {
		elem.addEventListener("keydown", async (event) => {
			if (event.which === 13) {
				await ban();
			}
		});
	}

	for (var elem of document.querySelectorAll("#add-item textarea")) {
		elem.addEventListener("keydown", async (event) => {
			if (event.which === 13 && event.ctrlKey) {
				await ban();
			}
		});
	}

	for (var row of document.querySelector("#bans").rows) {
		if (!row.querySelector(".update-ban")) {
			continue;
		}

		add_row_listeners(row);
	}
}


function page_user() {
	function add_row_listeners(row) {
		row.querySelector(".remove a").addEventListener("click", async (event) => {
			event.preventDefault();
			await del_user(row.id);
		});
	}


	async function add_user() {
		var elems = {
			username: document.getElementById("new-username"),
			password: document.getElementById("new-password"),
			password2: document.getElementById("new-password2"),
			handle: document.getElementById("new-handle")
		}

		var values = {
			username: elems.username.value.trim(),
			password: elems.password.value.trim(),
			password2: elems.password2.value.trim(),
			handle: elems.handle.value.trim()
		}

		if (values.username === "" | values.password === "" | values.password2 === "") {
			toast("Username, password, and password2 are required");
			return;
		}

		if (values.password !== values.password2) {
			toast("Passwords do not match");
			return;
		}

		try {
			var user = await request("POST", "v1/user", values);

		} catch (err) {
			toast(err);
			return
		}

		var row = append_table_row(document.querySelector("fieldset.section table"), user.username, {
			domain: user.username,
			handle: user.handle ? self.handle : "n/a",
			date: get_date_string(user.created),
			remove: `<a href="#" title="Delete User">&#10006;</a>`
		});

		add_row_listeners(row);

		elems.username.value = null;
		elems.password.value = null;
		elems.password2.value = null;
		elems.handle.value = null;

		document.querySelector("details.section").open = false;
		toast("Created user", "message");
	}


	async function del_user(username) {
		try {
			await request("DELETE", "v1/user", {"username": username});
	
		} catch (error) {
			toast(error);
			return;
		}

		document.getElementById(username).remove();
		toast("Deleted user", "message");
	}


	document.querySelector("#new-user").addEventListener("click", async (event) => {
		await add_user();
	});

	for (var elem of document.querySelectorAll("#add-item input")) {
		elem.addEventListener("keydown", async (event) => {
			if (event.which === 13) {
				await add_user();
			}
		});
	}

	for (var row of document.querySelector("#users").rows) {
		if (!row.querySelector(".remove a")) {
			continue;
		}

		add_row_listeners(row);
	}
}


function page_whitelist() {
	function add_row_listeners(row) {
		row.querySelector(".remove a").addEventListener("click", async (event) => {
			event.preventDefault();
			await del_whitelist(row.id);
		});
	}


	async function add_whitelist() {
		var domain_elem = document.getElementById("new-domain");
		var domain = domain_elem.value.trim();

		if (domain === "") {
			toast("Domain is required");
			return;
		}

		try {
			var item = await request("POST", "v1/whitelist", {"domain": domain});

		} catch (err) {
			toast(err);
			return;
		}

		var row = append_table_row(document.getElementById("whitelist"), item.domain, {
			domain: item.domain,
			date: get_date_string(item.created),
			remove: `<a href="#" title="Remove whitelisted domain">&#10006;</a>`
		});

		add_row_listeners(row);

		domain_elem.value = null;
		document.querySelector("details.section").open = false;
		toast("Added domain", "message");
	}


	async function del_whitelist(domain) {
		try {
			await request("DELETE", "v1/whitelist", {"domain": domain});

		} catch (error) {
			toast(error);
			return;
		}

		document.getElementById(domain).remove();
		toast("Removed domain", "message");
	}


	document.querySelector("#new-item").addEventListener("click", async (event) => {
		await add_whitelist();
	});

	document.querySelector("#add-item").addEventListener("keydown", async (event) => {
		if (event.which === 13) {
			await add_whitelist();
		}
	});

	for (var row of document.querySelector("fieldset.section table").rows) {
		if (!row.querySelector(".remove a")) {
			continue;
		}

		add_row_listeners(row);
	}
}


if (location.pathname.startsWith("/admin/config")) {
	page_config();

} else if (location.pathname.startsWith("/admin/domain_bans")) {
	page_domain_ban();

} else if (location.pathname.startsWith("/admin/instances")) {
	page_instance();

} else if (location.pathname.startsWith("/admin/software_bans")) {
	page_software_ban();

} else if (location.pathname.startsWith("/admin/users")) {
	page_user();

} else if (location.pathname.startsWith("/admin/whitelist")) {
	page_whitelist();

} else if (location.pathname.startsWith("/login")) {
	page_login();
}
