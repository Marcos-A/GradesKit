"""Read and write the Moodle assignment grading worksheet.

The worksheet is the CSV from "Download grading worksheet" (Catalan:
"Descarrega el full de càlcul per qualificar"). When it is uploaded again,
Moodle finds the identifier, grade, "last modified (grade)" and feedback
columns by their *exact* header text in the teacher's current language. So
the header row is never rewritten: we only change grade and feedback cells.

The header strings below come from the official Moodle language packs.
"""

import csv
import io
import re
import unicodedata
from dataclasses import dataclass

from gradeskit.tabular import UTF8_BOM, decode_text, detect_delimiter, parse_number, strip_accents

ROLE_IDENTIFIER = "identifier"
ROLE_FULLNAME = "fullname"
ROLE_EMAIL = "email"
ROLE_GRADE = "grade"
ROLE_MAX_GRADE = "max_grade"
ROLE_CAN_CHANGE = "can_change"
ROLE_LAST_MODIFIED_GRADE = "last_modified_grade"
ROLE_FEEDBACK = "feedback"

# One entry per language: role -> header text as Moodle writes it.
WORKSHEET_HEADERS = {
    "ca": {
        ROLE_IDENTIFIER: "Identificador",
        ROLE_FULLNAME: "Nom complet",
        ROLE_EMAIL: "Adreça electrònica",
        ROLE_GRADE: "Qualificació",
        ROLE_MAX_GRADE: "Qualificació màxima",
        ROLE_CAN_CHANGE: "Es pot canviar la qualificació",
        ROLE_LAST_MODIFIED_GRADE: "Darrera modificació (qualificació)",
        ROLE_FEEDBACK: "Comentaris de retroacció.",
    },
    "es": {
        ROLE_IDENTIFIER: "Identificador",
        ROLE_FULLNAME: "Nombre completo",
        ROLE_EMAIL: "Dirección de correo",
        ROLE_GRADE: "Calificación",
        ROLE_MAX_GRADE: "Calificación máxima",
        ROLE_CAN_CHANGE: "La calificación puede ser cambiada",
        ROLE_LAST_MODIFIED_GRADE: "Última modificación (calificación)",
        ROLE_FEEDBACK: "Comentarios de retroalimentación",
    },
    "en": {
        ROLE_IDENTIFIER: "Identifier",
        ROLE_FULLNAME: "Full name",
        ROLE_EMAIL: "Email address",
        ROLE_GRADE: "Grade",
        ROLE_MAX_GRADE: "Maximum grade",
        ROLE_CAN_CHANGE: "Grade can be changed",
        ROLE_LAST_MODIFIED_GRADE: "Last modified (grade)",
        ROLE_FEEDBACK: "Feedback comments",
    },
    "gl": {
        ROLE_IDENTIFIER: "Identificador",
        ROLE_FULLNAME: "Nome completo",
        ROLE_EMAIL: "Enderezo de correo",
        ROLE_GRADE: "Cualificación",
        ROLE_MAX_GRADE: "Cualificación máxima",
        ROLE_CAN_CHANGE: "A cualificación pode seren cambiada",
        ROLE_LAST_MODIFIED_GRADE: "Última modificación (cualificación)",
        ROLE_FEEDBACK: "Comentarios",
    },
    "eu": {
        ROLE_IDENTIFIER: "Identifikatzailea",
        ROLE_FULLNAME: "Izen osoa",
        ROLE_EMAIL: "Helbide elektronikoa",
        ROLE_GRADE: "Kalifikazioa",
        ROLE_MAX_GRADE: "Gehieneko kalifikazioa",
        ROLE_CAN_CHANGE: "Kalifikazioa alda daiteke",
        ROLE_LAST_MODIFIED_GRADE: "Azken aldaketa (kalifikazioa)",
        ROLE_FEEDBACK: "Feedback-iruzkinak",
    },
    "fr": {
        ROLE_IDENTIFIER: "Identifiant",
        ROLE_FULLNAME: "Nom complet",
        ROLE_EMAIL: "Adresse de courriel",
        ROLE_GRADE: "Note",
        ROLE_MAX_GRADE: "Note maximale",
        ROLE_CAN_CHANGE: "La note peut être modifiée",
        ROLE_LAST_MODIFIED_GRADE: "Dernière modification (note)",
        ROLE_FEEDBACK: "Feedback par commentaires",
    },
    "pt": {
        ROLE_IDENTIFIER: "Identificador",
        ROLE_FULLNAME: "Nome completo",
        ROLE_EMAIL: "E-mail",
        ROLE_GRADE: "Avaliação",
        ROLE_MAX_GRADE: "Nota máxima",
        ROLE_CAN_CHANGE: "A nota pode ser alterada.",
        ROLE_LAST_MODIFIED_GRADE: "Última atualização (avaliação)",
        ROLE_FEEDBACK: "Comentários de feedback",
    },
    "it": {
        ROLE_IDENTIFIER: "Identificativo",
        ROLE_FULLNAME: "Nome",
        ROLE_EMAIL: "Indirizzo email",
        ROLE_GRADE: "Valutazione",
        ROLE_MAX_GRADE: "Valutazione massima",
        ROLE_CAN_CHANGE: "La valutazione può essere cambiata",
        ROLE_LAST_MODIFIED_GRADE: "Ultima modifica (valutazione)",
        ROLE_FEEDBACK: "Commenti",
    },
    "de": {
        ROLE_IDENTIFIER: "ID",
        ROLE_FULLNAME: "Vollständiger Name",
        ROLE_EMAIL: "E-Mail-Adresse",
        ROLE_GRADE: "Bewertung",
        ROLE_MAX_GRADE: "Bestwertung",
        ROLE_CAN_CHANGE: "Bewertung kann geändert werden",
        ROLE_LAST_MODIFIED_GRADE: "Zuletzt geändert (Bewertung)",
        ROLE_FEEDBACK: "Feedback als Kommentar",
    },
}
LANGUAGE_NAMES = {
    "ca": "català",
    "es": "castellà",
    "en": "anglès",
    "gl": "gallec",
    "eu": "basc",
    "fr": "francès",
    "pt": "portuguès",
    "it": "italià",
    "de": "alemany",
}
# Values of the "grade can be changed" column that mean "no".
CANNOT_CHANGE_VALUES = {"no", "non", "nein", "ez", "nao"}
PARTICIPANT_ID_PATTERN = re.compile(r"^\D*\d+$")

UNRECOGNIZED_WORKSHEET_MESSAGE = (
    "No hem reconegut el full de qualificacions de la tasca. Descarrega'l des de la tasca del Moodle "
    "amb «Descarrega el full de càlcul per qualificar» i puja'l sense modificar."
)
NO_NAMES_MESSAGE = (
    "El full de qualificacions no inclou els noms dels estudiants. "
    "Si la tasca té les trameses anònimes activades, no es poden relacionar amb les notes finals."
)


def _normalize_header(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip().rstrip(".").strip()
    return value.casefold()


@dataclass
class Worksheet:
    file_name: str
    rows: list[list[str]]
    language: str | None
    columns: dict[str, int]
    decimal_separator: str
    line_terminator: str
    has_bom: bool

    @property
    def header(self) -> list[str]:
        return self.rows[0]

    def participant_rows(self) -> list[int]:
        identifier = self.columns[ROLE_IDENTIFIER]
        return [
            index
            for index in range(1, len(self.rows))
            if identifier < len(self.rows[index]) and self.rows[index][identifier].strip()
        ]

    def cell(self, row_index: int, role: str) -> str:
        column = self.columns.get(role)
        row = self.rows[row_index]
        if column is None or column >= len(row):
            return ""
        return row[column].strip()

    def max_grade(self) -> float | None:
        values = {self.cell(row, ROLE_MAX_GRADE) for row in self.participant_rows()} - {""}
        numbers = [parse_number(value) for value in values]
        numbers = [number for number in numbers if number is not None]
        return max(numbers) if numbers else None

    def grade_can_change(self, row_index: int) -> bool:
        value = strip_accents(self.cell(row_index, ROLE_CAN_CHANGE)).casefold()
        return value not in CANNOT_CHANGE_VALUES

    def to_preview(self) -> dict:
        def header_for(role: str) -> str | None:
            column = self.columns.get(role)
            return self.header[column] if column is not None else None

        return {
            "file_name": self.file_name,
            "language": self.language,
            "language_name": LANGUAGE_NAMES.get(self.language, "desconegut"),
            "participants": len(self.participant_rows()),
            "grade_header": header_for(ROLE_GRADE),
            "feedback_header": header_for(ROLE_FEEDBACK),
            "max_grade": self.max_grade(),
        }


def _detect_columns(header: list[str], rows: list[list[str]]) -> tuple[str | None, dict[str, int]]:
    """Map worksheet roles to column indexes and guess the Moodle language."""

    normalized = [_normalize_header(cell) for cell in header]
    best_language, best_columns = None, {}
    for language, headers in WORKSHEET_HEADERS.items():
        columns = {}
        for role, text in headers.items():
            target = _normalize_header(text)
            if target in normalized:
                columns[role] = normalized.index(target)
        if len(columns) > len(best_columns):
            best_language, best_columns = language, columns

    # A customised language pack may rename a few strings; borrow any role we
    # can still recognise from another language.
    for headers in WORKSHEET_HEADERS.values():
        for role, text in headers.items():
            target = _normalize_header(text)
            if role not in best_columns and target in normalized and normalized.index(target) not in best_columns.values():
                best_columns[role] = normalized.index(target)

    data_rows = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    if ROLE_IDENTIFIER not in best_columns:
        # Moodle identifiers look like "Participant1172217".
        for column in range(len(header)):
            values = [row[column].strip() for row in data_rows if column < len(row)]
            if values and all(PARTICIPANT_ID_PATTERN.match(value) for value in values):
                best_columns[ROLE_IDENTIFIER] = column
                break
    if ROLE_EMAIL not in best_columns:
        for column in range(len(header)):
            values = [row[column].strip() for row in data_rows if column < len(row)]
            if values and all("@" in value for value in values if value):
                best_columns[ROLE_EMAIL] = column
                break
    if ROLE_GRADE not in best_columns and ROLE_MAX_GRADE in best_columns:
        # The grade column always comes right before the maximum grade.
        best_columns[ROLE_GRADE] = best_columns[ROLE_MAX_GRADE] - 1
    if ROLE_FEEDBACK not in best_columns and ROLE_LAST_MODIFIED_GRADE in best_columns:
        # Feedback comments come right after "last modified (grade)".
        candidate = best_columns[ROLE_LAST_MODIFIED_GRADE] + 1
        if candidate < len(header):
            best_columns[ROLE_FEEDBACK] = candidate

    return best_language, best_columns


def read_worksheet(content: bytes, file_name: str) -> Worksheet:
    has_bom = content.startswith(UTF8_BOM.encode("utf-8"))
    text = decode_text(content)
    line_terminator = "\r\n" if "\r\n" in text else "\n"
    rows = list(csv.reader(io.StringIO(text), delimiter=detect_delimiter(text)))
    if len(rows) < 2:
        raise ValueError(UNRECOGNIZED_WORKSHEET_MESSAGE)

    language, columns = _detect_columns(rows[0], rows)
    if ROLE_IDENTIFIER not in columns or ROLE_GRADE not in columns:
        raise ValueError(UNRECOGNIZED_WORKSHEET_MESSAGE)
    if ROLE_FULLNAME not in columns and ROLE_EMAIL not in columns:
        raise ValueError(NO_NAMES_MESSAGE)

    worksheet = Worksheet(
        file_name=file_name,
        rows=rows,
        language=language,
        columns=columns,
        decimal_separator=",",
        line_terminator=line_terminator,
        has_bom=has_bom,
    )
    # Write grades with the same decimal separator Moodle used for the
    # maximum grade: Moodle parses them with the teacher's locale, where "."
    # can be a thousands separator.
    max_grades = [worksheet.cell(row, ROLE_MAX_GRADE) for row in worksheet.participant_rows()]
    if any("." in value and "," not in value for value in max_grades):
        worksheet.decimal_separator = "."
    return worksheet


def format_grade(value: float, decimal_separator: str) -> str:
    text = f"{value:.5f}".rstrip("0").rstrip(".")
    return text.replace(".", decimal_separator)


def write_worksheet(worksheet: Worksheet, updates: dict[int, dict[str, str]]) -> bytes:
    """Return the worksheet CSV with the given cells replaced.

    `updates` maps a row index to {role: new value}. Everything else is kept,
    including the header row. The output is always UTF-8 and comma-separated,
    which are the defaults of Moodle's upload form.
    """

    rows = [list(row) for row in worksheet.rows]
    for row_index, values in updates.items():
        row = rows[row_index]
        for role, value in values.items():
            column = worksheet.columns[role]
            if column >= len(row):
                row.extend([""] * (column + 1 - len(row)))
            row[column] = value

    output = io.StringIO()
    writer = csv.writer(output, lineterminator=worksheet.line_terminator)
    writer.writerows(rows)
    text = output.getvalue()
    if worksheet.has_bom:
        text = UTF8_BOM + text
    return text.encode("utf-8")
