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
		alert("Actor is required");
		return;
	}

	try {
		var instance = await client.request("POST", "v1/instance", values);

	} catch (err) {
		alert(err);
		return
	}

	append_table_row(document.getElementById("instances"), instance.domain, {
		domain: `<a href="https://${instance.domain}/" target="_new">${instance.domain}</a>`,
		software: instance.software,
		date: get_date_string(instance.created),
		remove: `<a href="#" onclick="del_instance('${instance.domain}')" title="Remove Instance">&#10006;</a>`
	});

	elems.actor.value = null;
	elems.inbox.value = null;
	elems.followid.value = null;
	elems.software.value = null;

	document.querySelector("details.section").open = false;
}


async function del_instance(domain) {
	try {
		await client.request("DELETE", "v1/instance", {"domain": domain});

	} catch (error) {
		alert(error);
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
		await client.request("POST", "v1/request", params);

	} catch (error) {
		alert(error);
		return;
	}

	document.getElementById(domain).remove();

	if (document.getElementById("requests").rows.length < 2) {
		document.querySelector("fieldset.requests").remove()
	}

	if (!accept) {
		return;
	}

	instances = await client.request("GET", `v1/instance`, null);
	instances.forEach((instance) => {
		if (instance.domain === domain) {
			append_table_row(document.getElementById("instances"), instance.domain, {
				domain: `<a href="https://${instance.domain}/" target="_new">${instance.domain}</a>`,
				software: instance.software,
				date: get_date_string(instance.created),
				remove: `<a href="#" onclick="del_instance('${instance.domain}')" title="Remove Instance">&#10006;</a>`
			});
		}
	});
}
