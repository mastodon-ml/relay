async function login(event) {
	fields = {
		username: document.querySelector("#username"),
		password: document.querySelector("#password")
	}

	values = {
		username: fields.username.value.trim(),
		password: fields.password.value.trim()
	}

	if (values.username === "" | values.password === "") {
		toast("Username and/or password field is blank");
		return;
	}

	try {
		await request("POST", "v1/token", values);

	} catch (error) {
		toast(error);
		return;
	}

	document.location = "/";
}


document.querySelector(".submit").addEventListener("click", login);
