function create_ban_object(name, reason, note) {
	var text = '<details>\n';
	text += `<summary>${name}</summary>\n`;
	text += '<div class="grid-2col">\n';
	text += `<label for="${name}-reason" class="reason">Reason</label>\n`;
	text += `<textarea id="${name}-reason" class="reason">${reason}</textarea>\n`;
	text += `<label for="${name}-note" class="note">Note</label>\n`;
	text += `<textarea id="${name}-note" class="note">${note}</textarea>\n`;
	text += `<input type="button" value="Update" onclick="update_ban(\"${name}\"")">`;
	text += '</details>';

	return text;
}


async function ban() {
	var table = document.querySelector("table");
	var row = table.insertRow(-1);

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
		alert("Domain is required");
		return;
	}

	try {
		var ban = await client.request("POST", "v1/software_ban", values);

	} catch (err) {
		alert(err);
		return
	}

	row.id = ban.name;
	var new_name = row.insertCell(0);
	var new_date = row.insertCell(1);
	var new_remove = row.insertCell(2);

	new_name.className = "name";
	new_date.className = "date";
	new_remove.className = "remove";

	new_name.innerHTML = create_ban_object(ban.name, ban.reason, ban.note);
	new_date.innerHTML = get_date_string(ban.created);
	new_remove.innerHTML = `<a href="#" onclick="unban('${ban.name}')" title="Unban name">&#10006;</a>`;

	elems.name.value = null;
	elems.reason.value = null;
	elems.note.value = null;

	document.querySelector("details.section").open = false;
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
		await client.request("PATCH", "v1/software_ban", values)

	} catch (error) {
		alert(error);
		return;
	}

	row.querySelector("details").open = false;
}


async function unban(name) {
	try {
		await client.request("DELETE", "v1/software_ban", {"name": name});

	} catch (error) {
		alert(error);
		return;
	}

	document.getElementById(name).remove();
}
