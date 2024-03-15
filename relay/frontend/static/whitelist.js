async function add_whitelist() {
	var domain_elem = document.getElementById("new-domain");
	var domain = domain_elem.value.trim();

	if (domain === "") {
		alert("Domain is required");
		return;
	}

	try {
		var item = await request("POST", "v1/whitelist", {"domain": domain});

	} catch (err) {
		alert(err);
		return
	}

	append_table_row(document.getElementById("whitelist"), item.domain, {
		domain: item.domain,
		date: get_date_string(item.created),
		remove: `<a href="#" onclick="del_whitelist('${item.domain}')" title="Remove whitelisted domain">&#10006;</a>`
	});

	domain_elem.value = null;
	document.querySelector("details.section").open = false;
}


async function del_whitelist(domain) {
	try {
		await request("DELETE", "v1/whitelist", {"domain": domain});

	} catch (error) {
		alert(error);
		return;
	}

	document.getElementById(domain).remove();
}
