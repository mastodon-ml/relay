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

for (var row of document.querySelector("#bans").rows) {
	if (!row.querySelector(".update-ban")) {
		continue;
	}

	add_row_listeners(row);
}
