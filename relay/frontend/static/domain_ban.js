function create_ban_object(domain, reason, note) {
	var text = '<details>\n';
	text += `<summary>${domain}</summary>\n`;
	text += '<div class="grid-2col">\n';
	text += `<label for="${domain}-reason" class="reason">Reason</label>\n`;
	text += `<textarea id="${domain}-reason" class="reason">${reason}</textarea>\n`;
	text += `<label for="${domain}-note" class="note">Note</label>\n`;
	text += `<textarea id="${domain}-note" class="note">${note}</textarea>\n`;
	text += `<input type="button" value="Update" onclick="update_ban(\"${domain}\"")">`;
	text += '</details>';

	return text;
}


async function ban() {
	var table = document.querySelector("table");
	var row = table.insertRow(-1);

	var elems = {
		domain: document.getElementById("new-domain"),
		reason: document.getElementById("new-reason"),
		note: document.getElementById("new-note")
	}

	var values = {
		domain: elems.domain.value.trim(),
		reason: elems.reason.value,
		note: elems.note.value
	}

	if (values.domain === "") {
		alert("Domain is required");
		return;
	}

	try {
		var ban = await client.ban(values.domain, values.reason, values.note);

	} catch (err) {
		alert(err);
		return
	}

	row.id = ban.domain;
	var new_domain = row.insertCell(0);
	var new_date = row.insertCell(1);
	var new_remove = row.insertCell(2);

	new_domain.className = "domain";
	new_date.className = "date";
	new_remove.className = "remove";

	new_domain.innerHTML = create_ban_object(ban.domain, ban.reason, ban.note);
	new_date.innerHTML = get_date_string(ban.created);
	new_remove.innerHTML = `<a href="#" onclick="unban('${ban.domain}')" title="Unban domain">&#10006;</a>`;

	elems.domain.value = null;
	elems.reason.value = null;
	elems.note.value = null;

	row.querySelector("details").open = false;
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
		await client.request("PATCH", "v1/domain_ban", values)

	} catch (error) {
		alert(error);
		return;
	}

	row.querySelector("details").open = false;
}


async function unban(domain) {
	try {
		await client.unban(domain);

	} catch (error) {
		alert(error);
		return;
	}

	document.getElementById(domain).remove();
}
