const elems = [
	document.querySelector("#name"),
	document.querySelector("#description"),
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
		await client.request("POST", "v1/config", params);

	} catch (error) {
		alert(error);
		return;
	}

	if (params.key === "name") {
		document.querySelector("#header .title").innerHTML = params.value;
		document.querySelector("title").innerHTML = params.value;
	}
}


for (const elem of elems) {
	elem.addEventListener("change", handle_config_change);
}
