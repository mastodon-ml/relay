const fields = {
	username: document.querySelector("#username"),
	password: document.querySelector("#password")
}

async function login(event) {
	const values = {
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


document.querySelector("#username").addEventListener("keydown", async (event) => {
	if (event.which === 13) {
		fields.password.focus();
		fields.password.select();
	}
});

document.querySelector("#password").addEventListener("keydown", async (event) => {
	if (event.which === 13) {
		await login(event);
	}
});

document.querySelector(".submit").addEventListener("click", login);
