const body = document.getElementById("container")
const menu = document.getElementById("menu");
const menu_open = document.getElementById("menu-open");
const menu_close = document.getElementById("menu-close");

menu_open.addEventListener("click", (event) => {
	var new_value = menu.attributes.visible.nodeValue === "true" ? "false" : "true";
	menu.attributes.visible.nodeValue = new_value;
});

menu_close.addEventListener("click", (event) => {
	menu.attributes.visible.nodeValue = "false"
});

body.addEventListener("click", (event) => {
	if (event.target === menu_open) {
		return;
	}

	menu.attributes.visible.nodeValue = "false";
});
