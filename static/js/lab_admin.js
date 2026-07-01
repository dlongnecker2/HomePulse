function setAdminStatus(message) {
  const element = document.getElementById("admin-action-status");
  if (element) element.textContent = message;
}

async function runAdminAction(action) {
  const label = action === "shutdown" ? "Stop HomePulse" : "Restart HomePulse";
  const prompt = action === "shutdown" ? "Stop HomePulse now?" : "Restart HomePulse now?";
  if (!window.confirm(prompt)) return;
  setAdminStatus(`${label} requested...`);
  try {
    const response = await fetch(`/api/system/${action}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-HomePulse-Admin-Token": window.HomePulseAdminActionToken || "",
      },
      body: JSON.stringify({ admin_token: window.HomePulseAdminActionToken || "" }),
    });
    const payload = await response.json();
    setAdminStatus(payload.message || `${label} response: ${response.status}`);
  } catch (error) {
    setAdminStatus(`${label} request failed. Check logs for details.`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-admin-action]").forEach((button) => {
    button.addEventListener("click", () => runAdminAction(button.dataset.adminAction));
  });
});
