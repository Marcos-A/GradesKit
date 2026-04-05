"""Small WSGI web app for uploading Moodle exports and downloading merged results.

The server is intentionally built on Python's standard library so the Docker
image can run in restricted environments without installing extra packages.
"""

import cgi
import os
from html import escape as html_escape
from http import HTTPStatus
from wsgiref.simple_server import make_server

from merger import (
    InputFile,
    RESULT_FILE_NAME,
    STRATEGY_AVERAGE,
    STRATEGY_HIGHEST,
    STRATEGY_WEIGHTED,
    build_result_matrix,
    extract_input_files,
    normalize_percent,
    rows_to_csv_bytes,
    rows_to_xlsx_bytes,
)


def render_page(error_message: str = "", form_values: dict[str, str] | None = None) -> bytes:
    """Render the single-page upload form.

    The page is generated inline instead of using a template engine so the app
    stays dependency-free.
    """

    values = {
        "strategy": STRATEGY_WEIGHTED,
        "weighted_percent": "80%",
        "output_format": "xlsx",
    }
    if form_values:
        values.update(form_values)

    # The weighted card keeps its place in the desktop grid even when hidden,
    # so the neighboring cards do not jump around when the strategy changes.
    weighted_hidden_class = "" if values["strategy"] == STRATEGY_WEIGHTED else " is-hidden"
    error_html = (
        f'<div class="alert error">{html_escape(error_message)}</div>'
        if error_message
        else ""
    )

    html = f"""<!doctype html>
<html lang="ca">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Combinador de qualificacions Moodle</title>
    <link rel="stylesheet" href="/static/style.css">
  </head>
  <body>
    <main class="shell">
      <section class="panel hero">
        <p class="eyebrow">Flux de qualificacions Moodle</p>
        <h1>Combina els resultats de diversos qüestionaris en un únic fitxer descarregable.</h1>
        <p class="lead">
          Puja els fitxers CSV dels resultats exportats des de Moodle i l’aplicació els combina en un sol fitxer.
          Pots descarregar el resultat final en format CSV o XLSX.
        </p>
        <p class="lead lead-note">
          Aquesta versió reconeix els fitxers exportats des de la versió en català de Moodle.
        </p>
      </section>

      <section class="panel form-panel">
        <div class="alerts" id="form-alerts">{error_html}</div>
        <form action="/merge" method="post" enctype="multipart/form-data" class="merge-form" id="merge-form">
          <div class="grid">
            <div class="field field-upload">
              <span>Origen de la pujada</span>
              <input type="file" id="file-input" accept=".csv,.zip" multiple hidden>
              <div class="upload-zone" id="upload-zone" tabindex="0">
                <strong>Fes clic per seleccionar fitxers</strong>
                <span>per pujar un o més fitxers CSV, o bé un fitxer ZIP amb els CSV a dins.</span>
              </div>
              <div class="upload-list" id="upload-list">
                <span class="upload-placeholder">Encara no s'ha seleccionat cap fitxer.</span>
              </div>
              <small>Pots pujar un o més fitxers CSV directament, o un únic fitxer ZIP que els contingui. Els noms de columna han de correspondre a l'exportació en català de Moodle.</small>
            </div>

            <label class="field field-strategy">
              <span>Estratègia de qualificació</span>
              <select name="strategy" id="strategy" class="strategy-select">
                <option value="{STRATEGY_HIGHEST}" {"selected" if values["strategy"] == STRATEGY_HIGHEST else ""}>Només la nota més alta</option>
                <option value="{STRATEGY_AVERAGE}" {"selected" if values["strategy"] == STRATEGY_AVERAGE else ""}>Mitjana de les notes vàlides</option>
                <option value="{STRATEGY_WEIGHTED}" {"selected" if values["strategy"] == STRATEGY_WEIGHTED else ""}>Ponderar la nota més alta</option>
              </select>
              <small>Els intents amb una nota de zero o sense lliurament s'ignoren.</small>
            </label>

            <label class="field field-weighted{weighted_hidden_class}" id="weighted-percent-field">
              <span>Percentatge de la nota més alta</span>
              <input type="text" name="weighted_percent" id="weighted-percent-input" value="{html_escape(values['weighted_percent'], quote=True)}" placeholder="80%" inputmode="decimal" autocomplete="off">
              <small id="weighted-percent-help">Exemples acceptats: <code>80%</code>, <code>80</code> o <code>0,8%</code>.</small>
            </label>

            <label class="field field-download">
              <span>Format de descàrrega</span>
              <select name="output_format">
                <option value="csv" {"selected" if values["output_format"] == "csv" else ""}>CSV</option>
                <option value="xlsx" {"selected" if values["output_format"] == "xlsx" else ""}>XLSX</option>
              </select>
              <small>El fitxer generat es descarrega immediatament després del processament.</small>
            </label>
          </div>

          <button type="submit">Genera el fitxer combinat</button>
        </form>
      </section>
    </main>

    <script>
      const mergeForm = document.getElementById("merge-form");
      const fileInput = document.getElementById("file-input");
      const uploadZone = document.getElementById("upload-zone");
      const uploadList = document.getElementById("upload-list");
      const formAlerts = document.getElementById("form-alerts");
      const strategySelect = document.getElementById("strategy");
      const weightedField = document.getElementById("weighted-percent-field");
      const weightedPercentInput = document.getElementById("weighted-percent-input");
      const stagedFiles = [];

      function clearErrorAlert() {{
        formAlerts.innerHTML = "";
      }}

      function clearStagedFilesWithTransition() {{
        const chips = Array.from(uploadList.querySelectorAll(".upload-chip"));
        if (chips.length === 0) {{
          stagedFiles.length = 0;
          renderUploadList();
          return;
        }}

        uploadList.classList.add("is-clearing");
        for (const chip of chips) {{
          chip.classList.add("is-removing");
        }}

        window.setTimeout(() => {{
          stagedFiles.length = 0;
          uploadList.classList.remove("is-clearing");
          renderUploadList();
        }}, 220);
      }}

      function resetRetryState() {{
        clearErrorAlert();
        clearStagedFilesWithTransition();
      }}

      function syncWeightedField() {{
        // Hide the percentage card when it does not apply, but keep its grid
        // slot reserved so the surrounding layout stays stable.
        const isWeighted = strategySelect.value === "{STRATEGY_WEIGHTED}";
        weightedField.classList.toggle("is-hidden", !isWeighted);
        weightedPercentInput.disabled = !isWeighted;
        weightedPercentInput.setAttribute("aria-disabled", String(!isWeighted));
      }}

      function normalizeWeightedPercentValue(value, finalize = false) {{
        // The field is percentage-oriented in the UI. We accept flexible input
        // while the user types, then normalize it to a clean percentage string.
        let cleaned = value.replace(/\\s+/g, "").replace(/\\./g, ",");
        const hadPercent = cleaned.includes("%");
        cleaned = cleaned.replace(/[^0-9,%]/g, "");

        const parts = cleaned.replace(/%/g, "").split(",");
        const integerPart = parts[0] || "";
        const decimalPart = parts.slice(1).join("");

        if (!integerPart && !decimalPart) {{
          return "";
        }}

        let normalized = integerPart;
        if (parts.length > 1) {{
          normalized += `,${{decimalPart}}`;
        }}

        if (normalized === ",") {{
          return "";
        }}

        const numeric = Number(normalized.replace(",", "."));
        if (Number.isNaN(numeric)) {{
          return "";
        }}

        if (numeric > 100) {{
          normalized = "100";
        }}

        const shouldAppendPercent = finalize || hadPercent;
        if (normalized.endsWith(",")) {{
          return normalized;
        }}

        return shouldAppendPercent ? `${{normalized}}%` : normalized;
      }}

      function renderUploadList() {{
        if (stagedFiles.length === 0) {{
          uploadList.innerHTML = '<span class="upload-placeholder">Encara no s\\'ha seleccionat cap fitxer.</span>';
          return;
        }}

        uploadList.innerHTML = stagedFiles
          .map((file) => `<span class="upload-chip">${{file.relativePath || file.name}}</span>`)
          .join("");
      }}

      function addFiles(files) {{
        clearErrorAlert();
        // Avoid showing the same file twice if the browser fires repeated
        // change events or the user selects the same file again accidentally.
        for (const file of files) {{
          const duplicate = stagedFiles.some(
            (item) => item.name === file.name && item.size === file.size && item.relativePath === file.relativePath
          );
          if (!duplicate) {{
            stagedFiles.push(file);
          }}
        }}
        renderUploadList();
      }}

      function clearFilesWithTransition() {{
        // Successful downloads clear the staged list, but with a brief fade so
        // the reset feels intentional instead of abrupt.
        clearStagedFilesWithTransition();
      }}

      // The visible upload area is a custom control. It delegates to a hidden
      // native file input so the browser still handles file permissions.
      uploadZone.addEventListener("click", () => {{
        resetRetryState();
        fileInput.click();
      }});
      uploadZone.addEventListener("keydown", (event) => {{
        if (event.key === "Enter" || event.key === " ") {{
          event.preventDefault();
          resetRetryState();
          fileInput.click();
        }}
      }});

      fileInput.addEventListener("change", () => {{
        addFiles(Array.from(fileInput.files || []));
        fileInput.value = "";
      }});

      weightedPercentInput.addEventListener("input", () => {{
        weightedPercentInput.value = normalizeWeightedPercentValue(weightedPercentInput.value);
      }});

      weightedPercentInput.addEventListener("blur", () => {{
        weightedPercentInput.value = normalizeWeightedPercentValue(weightedPercentInput.value, true);
      }});

      mergeForm.addEventListener("submit", async (event) => {{
        event.preventDefault();
        weightedPercentInput.value = normalizeWeightedPercentValue(weightedPercentInput.value, true);

        const formData = new FormData(mergeForm);
        for (const file of stagedFiles) {{
          formData.append("csv_files", file, file.relativePath || file.name);
        }}

        // Submit through fetch so the page can keep its current state, surface
        // validation errors inline, and still trigger a direct file download.
        const response = await fetch("/merge", {{
          method: "POST",
          body: formData,
        }});

        const contentType = response.headers.get("Content-Type") || "";
        if (!response.ok && contentType.includes("text/html")) {{
          const errorPage = await response.text();
          const parsedDocument = new DOMParser().parseFromString(errorPage, "text/html");
          const nextError = parsedDocument.querySelector(".alert.error");
          formAlerts.innerHTML = nextError ? nextError.outerHTML : "";
          return;
        }}

        const blob = await response.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const contentDisposition = response.headers.get("Content-Disposition") || "";
        const fileNameMatch = contentDisposition.match(/filename="([^"]+)"/);
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = fileNameMatch ? fileNameMatch[1] : "resultat";
        document.body.appendChild(link);
        link.click();
        clearFilesWithTransition();
        link.remove();
        URL.revokeObjectURL(downloadUrl);
      }});

      strategySelect.addEventListener("change", syncWeightedField);
      syncWeightedField();
      renderUploadList();
    </script>
  </body>
</html>
"""
    return html.encode("utf-8")


def serve_static(path: str):
    """Serve files from `static/` for the lightweight WSGI server."""

    static_path = os.path.join(os.path.dirname(__file__), "static", path.removeprefix("/static/"))
    if not os.path.isfile(static_path):
        return HTTPStatus.NOT_FOUND, [("Content-Type", "text/plain; charset=utf-8")], b"Not found"

    mime_type = "text/css; charset=utf-8" if static_path.endswith(".css") else "application/octet-stream"
    with open(static_path, "rb") as static_file:
        return HTTPStatus.OK, [("Content-Type", mime_type)], static_file.read()


def parse_uploads(environ):
    """Extract uploaded files and form fields from a multipart POST request."""

    form = cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)

    uploaded_csv_files = []
    csv_field = form["csv_files"] if "csv_files" in form else []
    if isinstance(csv_field, list):
        csv_items = csv_field
    elif csv_field is not None:
        # `FieldStorage` returns either one item or a list depending on how many
        # files the browser sent for the same input name.
        csv_items = [csv_field]
    else:
        csv_items = []

    for item in csv_items:
        if item.filename:
            uploaded_csv_files.append(InputFile(name=item.filename, content=item.file.read()))

    # ZIP files travel through the same field as CSV files; `extract_input_files`
    # separates them later based on the file extension.
    form_values = {
        "strategy": form.getfirst("strategy", STRATEGY_WEIGHTED),
        "weighted_percent": form.getfirst("weighted_percent", "80%"),
        "output_format": form.getfirst("output_format", "xlsx"),
    }
    return uploaded_csv_files, None, form_values


def application(environ, start_response):
    """WSGI entrypoint used by the local server and the Docker container."""

    method = environ["REQUEST_METHOD"]
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/":
        payload = render_page()
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))])
        return [payload]

    if method == "GET" and path.startswith("/static/"):
        status, headers, payload = serve_static(path)
        start_response(f"{status.value} {status.phrase}", headers + [("Content-Length", str(len(payload)))])
        return [payload]

    if method == "POST" and path == "/merge":
        uploaded_csv_files, archive_file, form_values = parse_uploads(environ)
        try:
            # Validation lives close to request handling so users get a friendly
            # message instead of a server error page.
            weighted_percent = normalize_percent(form_values["weighted_percent"])
            input_files = extract_input_files(uploaded_csv_files, archive_file)
            rows = build_result_matrix(
                uploaded_files=input_files,
                strategy=form_values["strategy"],
                weighted_percent=weighted_percent,
            )
        except ValueError as error:
            payload = render_page(str(error), form_values)
            start_response(
                "400 Bad Request",
                [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(payload)))],
            )
            return [payload]

        if form_values["output_format"] == "xlsx":
            payload = rows_to_xlsx_bytes(rows)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            file_name = f"{RESULT_FILE_NAME}.xlsx"
        else:
            payload = rows_to_csv_bytes(rows)
            content_type = "text/csv; charset=utf-8"
            file_name = f"{RESULT_FILE_NAME}.csv"

        start_response(
            "200 OK",
            [
                ("Content-Type", content_type),
                ("Content-Disposition", f'attachment; filename="{file_name}"'),
                ("Content-Length", str(len(payload))),
            ],
        )
        return [payload]

    payload = b"Not found"
    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(payload)))])
    return [payload]


if __name__ == "__main__":
    # Bind to all interfaces so the app also works inside Docker.
    port = int(os.environ.get("PORT", "8000"))
    with make_server("0.0.0.0", port, application) as server:
        server.serve_forever()
