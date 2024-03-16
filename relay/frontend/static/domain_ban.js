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

for (var row of document.querySelector("fieldset.section table").rows) {
	if (!row.querySelector(".update-ban")) {
		continue;
	}

	add_row_listeners(row);
}
