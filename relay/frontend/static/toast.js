const notifications = document.querySelector("#notifications")


function remove_toast(toast) {
	toast.classList.add("hide");

	if (toast.timeoutId) {
		clearTimeout(toast.timeoutId);
	}

	setTimeout(() => toast.remove(), 300);
}

function toast(text, type="error", timeout=5) {
	const toast = document.createElement("li");
	toast.className = `section ${type}`
	toast.innerHTML = `<span class=".text">${text}</span><a href="#">&#10006;</span>`

	toast.querySelector("a").addEventListener("click", async (event) => {
		event.preventDefault();
		await remove_toast(toast);
	});

	notifications.appendChild(toast);
	toast.timeoutId = setTimeout(() => remove_toast(toast), timeout * 1000);
}
