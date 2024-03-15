async function add_whitelist() {
	var domain_elem = document.getElementById("new-domain");
	var domain = domain_elem.value.trim();

	if (domain === "") {
		alert("Domain is required");
		return;
	}

	try {
		var item = await client.request("POST", "v1/whitelist", {"domain": domain});

	} catch (err) {
		alert(err);
		return
	}

	var table = document.getElementById("whitelist");
	var row = table.insertRow(-1);
	row.id = item.domain;

	var domain = row.insertCell(0);
	domain.className = "domain";
	domain.innerHTML = item.domain;

	var date = row.insertCell(1);
	date.className = "date";
	date.innerHTML = get_date_string(item.created);

	var remove = row.insertCell(2);
	remove.className = "remove";
	remove.innerHTML = `<a href="#" onclick="del_whitelist('${item.domain}')" title="Remove whitelisted domain">&#10006;</a>`;

	domain_elem.value = null;
	document.querySelector("details.section").open = false;
}


async function del_whitelist(domain) {
	try {
		await client.request("DELETE", "v1/whitelist", {"domain": domain});

	} catch (error) {
		alert(error);
		return;
	}

	document.getElementById(domain).remove();
}
