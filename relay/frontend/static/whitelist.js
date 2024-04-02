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

for (var row of document.querySelector("fieldset.section table").rows) {
	if (!row.querySelector(".remove a")) {
		continue;
	}

	add_row_listeners(row);
}
