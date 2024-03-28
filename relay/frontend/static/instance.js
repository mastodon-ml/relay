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
