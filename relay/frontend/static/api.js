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

		if (Object.hasOwn(message, "created")) {
			message.created = new Date(message.created);
		}

		return message;
	}

	async ban(domain, reason, note) {
		const params = {
			"domain": domain,
			"reason": reason,
			"note": note
		}

		return await this.request("POST", "v1/domain_ban", params);
	}


	async unban(domain) {
		const params = {"domain": domain}
		return await this.request("DELETE", "v1/domain_ban", params);
	}
}


client = new Client();
