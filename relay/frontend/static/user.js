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
		alert("Username, password, and password2 are required");
		return;
	}

	if (values.password !== values.password2) {
		alert("Passwords do not match");
		return;
	}

	try {
		var user = await request("POST", "v1/user", values);

	} catch (err) {
		alert(err);
		return
	}

	append_table_row(document.getElementById("users"), user.username, {
		domain: user.username,
		handle: user.handle,
		date: get_date_string(user.created),
		remove: `<a href="#" onclick="del_user('${user.username}')" title="Delete User">&#10006;</a>`
	});

	elems.username.value = null;
	elems.password.value = null;
	elems.password2.value = null;
	elems.handle.value = null;

	document.querySelector("details.section").open = false;
}


async function del_user(username) {
	try {
		await request("DELETE", "v1/user", {"username": username});
 
	} catch (error) {
		alert(error);
		return;
	}

	document.getElementById(username).remove();
}
