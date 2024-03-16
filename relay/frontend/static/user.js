function add_row_listeners(row) {
	row.querySelector(".remove a").addEventListener("click", async (event) => {
		event.preventDefault();
		await del_user(row.id);
	});
}


async function add_user() {
	var elems = {
		username: document.getElementById("new-username"),
		password: document.getElementById("new-password"),
		password2: document.getElementById("new-password2"),
		handle: document.getElementById("new-handle")
	}

	var values = {
		username: elems.username.value.trim(),
		password: elems.password.value.trim(),
		password2: elems.password2.value.trim(),
		handle: elems.handle.value.trim()
	}

	if (values.username === "" | values.password === "" | values.password2 === "") {
		toast("Username, password, and password2 are required");
		return;
	}

	if (values.password !== values.password2) {
		toast("Passwords do not match");
		return;
	}

	try {
		var user = await request("POST", "v1/user", values);

	} catch (err) {
		toast(err);
		return
	}

	var row = append_table_row(document.querySelector("fieldset.section table"), user.username, {
		domain: user.username,
		handle: user.handle ? self.handle : "n/a",
		date: get_date_string(user.created),
		remove: `<a href="#" title="Delete User">&#10006;</a>`
	});

	add_row_listeners(row);

	elems.username.value = null;
	elems.password.value = null;
	elems.password2.value = null;
	elems.handle.value = null;

	document.querySelector("details.section").open = false;
	toast("Created user", "message");
}


async function del_user(username) {
	try {
		await request("DELETE", "v1/user", {"username": username});
 
	} catch (error) {
		toast(error);
		return;
	}

	document.getElementById(username).remove();
	toast("Deleted user", "message");
}


document.querySelector("#new-user").addEventListener("click", async (event) => {
	await add_user();
});

for (var row of document.querySelector("#users").rows) {
	if (!row.querySelector(".remove a")) {
		continue;
	}

	add_row_listeners(row);
}
