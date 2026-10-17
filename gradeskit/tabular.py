"""Read tabular data from uploaded CSV files or spreadsheet clipboard pastes.

Copying cells from Excel, LibreOffice or Google Sheets puts tab-separated
plain text on the clipboard with the *displayed* values, so a paste gives us
values only (no formulas or formatting). CSV files may use commas or
semicolons depending on the spreadsheet locale.
"""

import csv
import io
import unicodedata

UTF8_BOM = "\ufeff"
CANDIDATE_DELIMITERS = (";", ",")


def decode_text(content: bytes) -> str:
    """Decode UTF-8 (with or without BOM), falling back to Windows-1252.

    Excel on Windows still saves "CSV" files as Windows-1252 in many locales.
    """

    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def detect_delimiter(text: str) -> str:
    """Guess the delimiter of a CSV file or a clipboard paste.

    Spreadsheet pastes always use tabs, and real CSV files rarely contain them,
    so any tab wins. Otherwise we keep the delimiter that splits the first
    lines into the most consistent number of fields: decimal commas in a
    semicolon file make comma-splitting irregular.
    """

    if "\t" in text:
        return "\t"

    sample = "\n".join(text.splitlines()[:30])
    best_delimiter = ","
    best_score = (0.0, 0)
    for delimiter in CANDIDATE_DELIMITERS:
        widths = [
            len(row)
            for row in csv.reader(io.StringIO(sample), delimiter=delimiter)
            if any(cell.strip() for cell in row)
        ]
        if not widths:
            continue
        common_width = max(set(widths), key=widths.count)
        if common_width < 2:
            continue
        score = (widths.count(common_width) / len(widths), common_width)
        if score > best_score:
            best_delimiter, best_score = delimiter, score
    return best_delimiter


def parse_table(text: str) -> list[list[str]]:
    """Parse pasted or CSV text into a rectangular grid of trimmed strings.

    Fully empty rows and fully empty columns (spacer columns, trailing blank
    cells selected by accident) are dropped, so indexes refer to the cleaned
    grid that the user sees in the preview.
    """

    text = text.removeprefix(UTF8_BOM)
    if not text.strip():
        return []

    delimiter = detect_delimiter(text)
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text), delimiter=delimiter)
    ]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    kept_columns = [index for index in range(width) if any(row[index] for row in rows)]
    return [[row[index] for index in kept_columns] for row in rows]


def parse_number(value: str) -> float | None:
    """Read a number written with a decimal comma or point; None if it is not one."""

    cleaned = value.strip().replace(" ", "").replace("\u00a0", "")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        # The separator that appears last is the decimal one: "1.234,5" or "1,234.5".
        thousands = "." if cleaned.rfind(",") > cleaned.rfind(".") else ","
        cleaned = cleaned.replace(thousands, "")
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def column_letter(index: int) -> str:
    """Spreadsheet-style column label for a zero-based index (0 → A)."""

    label = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(65 + remainder) + label
    return label


def strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn"
    )
