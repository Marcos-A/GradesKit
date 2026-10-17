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

// --- Drag and drop onto upload zones -----------------------------------------

function hasDraggedFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

// A dropped file skips the input's `accept` filter, so check its extension.
function acceptsFile(input, file) {
  const name = file.name.toLowerCase();
  return input.accept.split(",").some((extension) => name.endsWith(extension.trim().toLowerCase()));
}

// Let `zone` take files dragged onto it, as if they were chosen in `input`.
// `onFiles` receives the accepted files (only the first one unless the input
// takes several); rejected files are reported in `alertsContainer`.
function bindFileDrop(zone, input, alertsContainer, onFiles) {
  zone.addEventListener("dragover", (event) => {
    if (!hasDraggedFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", (event) => {
    // Moving over the zone's own text also fires dragleave.
    if (!zone.contains(event.relatedTarget)) zone.classList.remove("dragover");
  });
  zone.addEventListener("drop", (event) => {
    if (!hasDraggedFiles(event)) return;
    event.preventDefault();
    zone.classList.remove("dragover");
    let files = Array.from(event.dataTransfer.files);
    if (!input.multiple) files = files.slice(0, 1);
    const accepted = files.filter((file) => acceptsFile(input, file));
    const rejected = files.filter((file) => !acceptsFile(input, file));
    if (accepted.length) onFiles(accepted);
    if (rejected.length) {
      const names = rejected.map((file) => `«${file.name}»`).join(", ");
      const types = input.accept.split(",").join(", ");
      showError(alertsContainer, `${rejected.length === 1 ? "Aquest fitxer no és" : "Aquests fitxers no són"} del tipus esperat (${types}): ${names}.`);
    }
  });
}

// A file dropped outside an upload zone would make the browser open it and
// lose the form, so ignore those drops.
window.addEventListener("dragover", (event) => {
  if (hasDraggedFiles(event)) event.preventDefault();
});
window.addEventListener("drop", (event) => {
  if (hasDraggedFiles(event)) event.preventDefault();
});
