"""Small WSGI web app that serves the GradesKit tools.

The server is intentionally built on Python's standard library so the Docker
image can run in restricted environments without installing extra packages.
"""

import cgi
import json
import os
from http import HTTPStatus
from string import Template
from urllib.parse import quote
from wsgiref.simple_server import make_server

from gradeskit.quiz_merge import (
    InputFile,
    RESULT_FILE_NAME,
    STRATEGY_AVERAGE,
    STRATEGY_HIGHEST,
    STRATEGY_WEIGHTED,
    build_result_matrix,
    extract_input_files,
    normalize_percent,
    rows_to_csv_bytes,
)
from gradeskit.fill import FillOptions, fill, preview
from gradeskit.moodle_worksheet import read_worksheet
from gradeskit.tabular import decode_text, parse_table
from gradeskit.xlsx import rows_to_xlsx_bytes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


def render_page() -> bytes:
    """Render the single-page UI from `templates/index.html`.

    `string.Template` keeps the app dependency-free; the page's JavaScript
    lives in `static/` so it never has to be escaped for Python formatting.
    """

    with open(os.path.join(BASE_DIR, "templates", "index.html"), encoding="utf-8") as template_file:
        template = Template(template_file.read())
    html = template.substitute(
        strategy_highest=STRATEGY_HIGHEST,
        strategy_average=STRATEGY_AVERAGE,
        strategy_weighted=STRATEGY_WEIGHTED,
    )
    return html.encode("utf-8")


def serve_static(path: str):
    """Serve files from `static/` for the lightweight WSGI server."""

    static_dir = os.path.join(BASE_DIR, "static")
    static_path = os.path.realpath(os.path.join(static_dir, path.removeprefix("/static/")))
    if not static_path.startswith(static_dir + os.sep) or not os.path.isfile(static_path):
        return HTTPStatus.NOT_FOUND, [("Content-Type", "text/plain; charset=utf-8")], b"Not found"

    mime_type = STATIC_MIME_TYPES.get(os.path.splitext(static_path)[1], "application/octet-stream")
    with open(static_path, "rb") as static_file:
        return HTTPStatus.OK, [("Content-Type", mime_type)], static_file.read()


def parse_form(environ) -> cgi.FieldStorage:
    return cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)


def uploaded_files(form: cgi.FieldStorage, field_name: str) -> list[InputFile]:
    """Return every file sent under `field_name`.

    `FieldStorage` returns either one item or a list depending on how many
    files the browser sent for the same input name.
    """

    if field_name not in form:
        return []
    field = form[field_name]
    items = field if isinstance(field, list) else [field]
    return [InputFile(name=item.filename, content=item.file.read()) for item in items if item.filename]


def json_response(start_response, status: HTTPStatus, data: dict):
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))],
    )
    return [payload]


def file_response(start_response, payload: bytes, content_type: str, file_name: str):
    # Moodle file names can contain accents, so send an ASCII fallback plus
    # the UTF-8 name (RFC 6266).
    ascii_name = file_name.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type),
            ("Content-Disposition", disposition),
            ("Content-Length", str(len(payload))),
        ],
    )
    return [payload]


def handle_merge(environ, start_response):
    form = parse_form(environ)
    try:
        # Validation lives close to request handling so users get a friendly
        # message instead of a server error page. ZIP files travel through the
        # same field as CSV files; `extract_input_files` separates them.
        weighted_percent = normalize_percent(form.getfirst("weighted_percent", "80%"))
        input_files = extract_input_files(uploaded_files(form, "csv_files"))
        rows = build_result_matrix(
            uploaded_files=input_files,
            strategy=form.getfirst("strategy", STRATEGY_WEIGHTED),
            weighted_percent=weighted_percent,
        )
    except ValueError as error:
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": str(error)})

    if form.getfirst("output_format", "xlsx") == "xlsx":
        return file_response(
            start_response,
            rows_to_xlsx_bytes(rows),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{RESULT_FILE_NAME}.xlsx",
        )
    return file_response(
        start_response,
        rows_to_csv_bytes(rows),
        "text/csv; charset=utf-8",
        f"{RESULT_FILE_NAME}.csv",
    )


def read_fill_inputs(form: cgi.FieldStorage):
    """Return the worksheet, the grades grid and the options sent by the fill tool.

    Grades come either from an uploaded CSV (`grades_file`) or from text
    pasted from a spreadsheet (`grades_text`). Missing inputs become None so
    the preview can describe whatever the user has provided so far.
    """

    worksheet_files = uploaded_files(form, "worksheet")
    worksheet = (
        read_worksheet(worksheet_files[0].content, worksheet_files[0].name) if worksheet_files else None
    )

    grades_files = uploaded_files(form, "grades_file")
    if grades_files:
        grades_text = decode_text(grades_files[0].content)
    else:
        grades_text = form.getfirst("grades_text", "")
    grade_rows = parse_table(grades_text) or None

    try:
        options = FillOptions.from_json(form.getfirst("options", ""))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Les opcions enviades no són vàlides.") from error
    return worksheet, grade_rows, options


def handle_fill_preview(environ, start_response):
    try:
        worksheet, grade_rows, options = read_fill_inputs(parse_form(environ))
        return json_response(start_response, HTTPStatus.OK, preview(worksheet, grade_rows, options))
    except ValueError as error:
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": str(error)})


def handle_fill(environ, start_response):
    try:
        worksheet, grade_rows, options = read_fill_inputs(parse_form(environ))
        if worksheet is None or grade_rows is None:
            raise ValueError("Cal el full de qualificacions de la tasca i les notes finals.")
        payload = fill(worksheet, grade_rows, options)
    except ValueError as error:
        return json_response(start_response, HTTPStatus.BAD_REQUEST, {"error": str(error)})

    stem = os.path.splitext(os.path.basename(worksheet.file_name))[0] or "full"
    return file_response(start_response, payload, "text/csv; charset=utf-8", f"{stem}-omplert.csv")


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
        return handle_merge(environ, start_response)

    if method == "POST" and path == "/api/fill/preview":
        return handle_fill_preview(environ, start_response)

    if method == "POST" and path == "/fill":
        return handle_fill(environ, start_response)

    payload = b"Not found"
    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(payload)))])
    return [payload]


if __name__ == "__main__":
    # Bind to all interfaces so the app also works inside Docker.
    port = int(os.environ.get("PORT", "8000"))
    with make_server("0.0.0.0", port, application) as server:
        server.serve_forever()
