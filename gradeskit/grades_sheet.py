"""Understand the teacher's own grades sheet.

A typical sheet has an optional title row ("TOTAL A1 (1a convocatòria)"), a
header row, one row per student, and optional footer rows with weights such
as "50%". This module guesses that structure; every guess can be overridden
from the UI.

Weights are read from percent cells ("50%") only, either in the footer rows
or in a row of percents above the header, and are shown next to each column
header in the feedback. Other footer values, such as maximum grades, are kept
apart so the teacher can choose to show them.
"""

import re
from dataclasses import dataclass, field

from gradeskit.quiz_merge import normalize_percent
from gradeskit.tabular import column_letter, parse_number

HEADER_SCAN_ROWS = 15
LETTER_PATTERN = re.compile(r"[^\W\d_]", re.UNICODE)
PERCENT_PATTERN = re.compile(r"^\d+(?:[.,]\d+)?\s*%$")
NO_NAME_COLUMN_MESSAGE = "No s'ha trobat cap columna amb els noms dels estudiants a les notes finals."
TOO_FEW_ROWS_MESSAGE = (
    "Les notes finals han de tenir com a mínim una fila de capçalera i una fila per estudiant."
)


@dataclass
class GradesSheet:
    rows: list[list[str]]
    header_row: int
    columns: list[str]
    name_column: int
    index_column: int | None
    grade_column: int
    feedback_columns: list[int]
    title: str
    student_rows: list[int] = field(default_factory=list)
    footer_rows: list[int] = field(default_factory=list)
    # Rows of percents above the header, kept out of the title.
    weight_rows: list[int] = field(default_factory=list)
    # Column -> (row, weight) for each percent cell found in the sheet.
    weight_cells: dict[int, tuple[int, str]] = field(default_factory=dict)

    @property
    def detected_weights(self) -> dict[int, str]:
        return {column: weight for column, (_, weight) in self.weight_cells.items()}

    def student_name(self, row_index: int) -> str:
        return self.rows[row_index][self.name_column]

    def footer_values(self, columns: list[int]) -> list[list[str]]:
        """Footer cells for `columns`, without the percents shown as weights."""

        used = {(row, column) for column, (row, _) in self.weight_cells.items()}
        return [
            ["" if (row, column) in used else self.rows[row][column] for column in columns]
            for row in self.footer_rows
        ]

    def to_preview(self) -> dict:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "header_row": self.header_row,
            "name_column": self.name_column,
            "index_column": self.index_column,
            "grade_column": self.grade_column,
            "feedback_columns": self.feedback_columns,
            "title": self.title,
            "student_rows": self.student_rows,
            "footer_rows": self.footer_rows,
            "weight_rows": self.weight_rows,
            # JSON object keys are strings.
            "detected_weights": {str(column): weight for column, weight in self.detected_weights.items()},
        }


def _filled(row: list[str]) -> int:
    return sum(1 for cell in row if cell)


def _looks_like_name(value: str) -> bool:
    return bool(value) and bool(LETTER_PATTERN.search(value)) and parse_number(value) is None


def is_percent(value: str) -> bool:
    return bool(PERCENT_PATTERN.match(value.strip()))


def _is_weights_row(row: list[str]) -> bool:
    return any(row) and all(is_percent(cell) for cell in row if cell)


def format_weight(value: str) -> str:
    """Write a weight typed or read as "50", "50 %", "12,5%" or "0,5" as "50%".

    Raises ValueError when the value is not a percentage.
    """

    percent = normalize_percent(value) * 100
    text = f"{percent:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text}%"


def detect_weights(
    rows: list[list[str]], weight_rows: list[int], footer_rows: list[int], columns: list[str]
) -> dict[int, tuple[int, str]]:
    """Find the first percent cell of each column in the weights and footer rows.

    Columns whose header already shows a percent ("Examen 50%") are skipped so
    the weight is not repeated.
    """

    cells: dict[int, tuple[int, str]] = {}
    for column, header in enumerate(columns):
        if "%" in header:
            continue
        for row in weight_rows + footer_rows:
            value = rows[row][column]
            if not is_percent(value):
                continue
            try:
                cells[column] = (row, format_weight(value))
            except ValueError:
                continue
            break
    return cells


def detect_header_row(rows: list[list[str]]) -> int:
    """The header is the first row that is (almost) as full as the widest rows.

    Title rows above it usually fill one cell, so they are skipped, and so is
    a row of weights ("40%", "60%").
    """

    scanned = rows[:HEADER_SCAN_ROWS]
    widest = max(_filled(row) for row in scanned)
    threshold = max(2, round(widest * 0.8))
    for index, row in enumerate(scanned[:-1]):
        if _filled(row) >= threshold and not _is_weights_row(row):
            return index
    return 0


def detect_name_column(rows: list[list[str]], header_row: int) -> int:
    """Pick the column whose values look most like person names."""

    data_rows = rows[header_row + 1 :]
    best_column, best_score = None, (0, 0)
    for column in range(len(rows[0])):
        values = [row[column] for row in data_rows]
        names = [value for value in values if _looks_like_name(value)]
        # Prefer "Cognoms, Nom" columns, then multi-word values.
        score = (len(names), sum(1 for value in names if "," in value or " " in value))
        if score > best_score:
            best_column, best_score = column, score
    if best_column is None:
        raise ValueError(NO_NAME_COLUMN_MESSAGE)
    return best_column


def detect_index_column(rows: list[list[str]], student_rows: list[int], name_column: int) -> int | None:
    """Find a row-counter column (1, 2, 3...) so it stays out of the feedback."""

    if not student_rows:
        return None
    for column in range(len(rows[0])):
        if column == name_column:
            continue
        values = [parse_number(rows[row][column]) for row in student_rows]
        if values == [float(position) for position in range(1, len(student_rows) + 1)]:
            return column
    return None


def analyse_grades_sheet(
    rows: list[list[str]],
    header_row: int | None = None,
    name_column: int | None = None,
    grade_column: int | None = None,
    feedback_columns: list[int] | None = None,
) -> GradesSheet:
    """Detect the sheet structure, honouring any choice the user already made."""

    if len(rows) < 2:
        raise ValueError(TOO_FEW_ROWS_MESSAGE)

    width = len(rows[0])
    if header_row is None or not 0 <= header_row < len(rows) - 1:
        header_row = detect_header_row(rows)
    if name_column is None or not 0 <= name_column < width:
        name_column = detect_name_column(rows, header_row)
    # The final grade is the last column unless the user picks another one.
    if grade_column is None or not 0 <= grade_column < width:
        grade_column = width - 1

    student_rows = [
        index
        for index in range(header_row + 1, len(rows))
        if _looks_like_name(rows[index][name_column])
    ]
    last_student = student_rows[-1] if student_rows else header_row
    # Rows after the last student without a name hold weights or maximums
    # ("50%", "10,00"). Percents become weights; the rest can be shown as a
    # footer.
    footer_rows = [
        index
        for index in range(last_student + 1, len(rows))
        if not _looks_like_name(rows[index][name_column]) and _filled(rows[index]) > 0
    ]

    index_column = detect_index_column(rows, student_rows, name_column)
    if feedback_columns is None:
        feedback_columns = [
            column for column in range(width) if column not in (name_column, index_column)
        ]
    else:
        feedback_columns = sorted({column for column in feedback_columns if 0 <= column < width})

    columns = [
        rows[header_row][column] or f"Columna {column_letter(column)}"
        for column in range(width)
    ]
    weight_rows = [index for index in range(header_row) if _is_weights_row(rows[index])]
    title = " · ".join(
        cell for index, row in enumerate(rows[:header_row]) if index not in weight_rows for cell in row if cell
    )

    return GradesSheet(
        rows=rows,
        header_row=header_row,
        columns=columns,
        name_column=name_column,
        index_column=index_column,
        grade_column=grade_column,
        feedback_columns=feedback_columns,
        title=title,
        student_rows=student_rows,
        footer_rows=footer_rows,
        weight_rows=weight_rows,
        weight_cells=detect_weights(rows, weight_rows, footer_rows, columns),
    )
