function get_cookie(name) {
	const regex = new RegExp(`(^| )` + name + `=([^;]+)`);
	const match = document.cookie.match(regex);

	if (match) {
		return match[2]
	}

	return null;
}


function get_date_string(date) {
	var year = date.getFullYear().toString();
	var month = date.getMonth().toString();
	var day = date.getDay().toString();

	if (month.length === 1) {
		month = "0" + month;
	}

	if (day.length === 1) {
		day = "0" + day
	}

	return `${year}-${month}-${day}`;
}


function append_table_row(table, row_name, row) {
	var table_row = table.insertRow(-1);
	table_row.id = row_name;

	index = 0;

	for (var prop in row) {
		if (Object.prototype.hasOwnProperty.call(row, prop)) {
			var cell = table_row.insertCell(index);
			cell.className = prop;
			cell.innerHTML = row[prop];

			index += 1;
		}
	}
}


class Client {
	constructor() {
		this.token = get_cookie("user-token");
	}


	async request(method, path, body = null) {
		var headers = {
			"Accept": "application/json"
		}

		if (body !== null) {
			headers["Content-Type"] = "application/json"
			body = JSON.stringify(body)
		}

		if (this.token !== null) {
			headers["Authorization"] = "Bearer " + this.token;
		}

		const response = await fetch("/api/" + path, {
			method: method,
			mode: "cors",
			cache: "no-store",
			redirect: "follow",
			body: body,
			headers: headers
		});

		const message = await response.json();

		if (Object.hasOwn(message, "error")) {
			throw new Error(message.error);
		}

		if (Array.isArray(message)) {
			message.forEach((msg) => {
				if (Object.hasOwn(msg, "created")) {
					msg.created = new Date(msg.created);
				}
			});

		} else {
			if (Object.hasOwn(message, "created")) {
				message.created = new Date(message.created);
			}
		}

		return message;
	}
}


client = new Client();
