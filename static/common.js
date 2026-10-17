// Helpers shared by the GradesKit tools.

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showError(container, message) {
  container.innerHTML = message ? `<div class="alert error">${escapeHtml(message)}</div>` : "";
}

// Error responses are JSON (`{"error": "..."}`); anything else is treated as
// a generic failure so the user still gets a message.
async function readError(response) {
  try {
    const data = await response.json();
    return data.error || "S'ha produït un error inesperat.";
  } catch {
    return "S'ha produït un error inesperat.";
  }
}

// Trigger a browser download for a successful file response.
async function downloadResponse(response, fallbackName) {
  const blob = await response.blob();
  const downloadUrl = URL.createObjectURL(blob);
  const contentDisposition = response.headers.get("Content-Disposition") || "";
  const fileNameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)|filename="([^"]+)"/);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = fileNameMatch
    ? decodeURIComponent(fileNameMatch[1] || fileNameMatch[2])
    : fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(downloadUrl);
}
