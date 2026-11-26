"""Understand the teacher's own grades sheet.

A typical sheet has an optional title row ("TOTAL A1 (1a convocatòria)"), a
header row, one row per student, and optional footer rows with weights such
as "50%". This module guesses that structure; every guess can be overridden
from the UI.

Some sheets have a two-row header: a group row with one label per activity
("Conceptes 01", merged over its columns) above the row with each column's
own label ("intent 1", "intent 2", "total"). Activities can have any number of
columns; one that takes a single column is a group of one, named by both
header cells ("Projecte" over "final") or by the top one alone when the cell
below is empty (a cell merged down).

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
PERSON_NAME_PATTERN = re.compile(r"^[^\W\d_][^\d]*[\s,][^\d]*[^\W\d_]$", re.UNICODE)
# Identifiers kept out of the feedback by default: DNI/NIE, e-mails, masked
# values ("****0528Q") and columns of large unique whole numbers (random keys).
DNI_PATTERN = re.compile(r"^[XYZ]?\d{7,8}[A-Z]$", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WHOLE_NUMBER_PATTERN = re.compile(r"^\d+$")
IDENTIFIER_SHARE = 0.8
GROUP_SEPARATOR = " · "
NO_NAME_COLUMN_MESSAGE = "No s'ha trobat cap columna amb els noms dels estudiants a les notes finals."
TOO_FEW_ROWS_MESSAGE = (
    "Les notes finals han de tenir com a mínim una fila de capçalera i una fila per estudiant."
)


@dataclass
class ColumnGroup:
    """One activity: its label and its columns, with each column's own label.

    A single-column group has an empty sub-label. In a group of several
    columns the last one holds the activity's result ("total").
    """

    label: str
    columns: list[int]
    subs: list[str]

    @property
    def result_column(self) -> int:
        return self.columns[-1]

    def to_preview(self) -> dict:
        return {"label": self.label, "columns": self.columns, "subs": self.subs}


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
    # Row with the activity labels above the header, if the header has two rows.
    group_row: int | None = None
    groups: list[ColumnGroup] = field(default_factory=list)
    # Columns of DNI, e-mails, keys... left out of the feedback by default.
    identifier_columns: list[int] = field(default_factory=list)

    @property
    def grouped(self) -> bool:
        """Whether some activity spans several columns."""

        return any(len(group.columns) > 1 for group in self.groups)

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
            "group_row": self.group_row,
            "groups": [group.to_preview() for group in self.groups],
            "grouped": self.grouped,
            "identifier_columns": self.identifier_columns,
            # JSON object keys are strings.
            "detected_weights": {str(column): weight for column, weight in self.detected_weights.items()},
        }


def _filled(row: list[str]) -> int:
    return sum(1 for cell in row if cell)


def looks_like_name(value: str) -> bool:
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


def _is_student_row(row: list[str]) -> bool:
    """A row with a person's name and mostly numbers in it."""

    filled = [cell for cell in row if cell]
    numbers = sum(1 for cell in filled if parse_number(cell) is not None)
    has_name = any(PERSON_NAME_PATTERN.match(cell) for cell in filled)
    return has_name and numbers >= 2 and numbers * 2 > len(filled)


def _is_group_row(row: list[str]) -> bool:
    return _filled(row) >= 2 and not _is_weights_row(row)


def detect_header_row(rows: list[list[str]]) -> int:
    """The header is the row just above the first student.

    Rows of weights ("40%", "60%") between them are skipped. Without a row
    that clearly holds a student, the header is the first row that is (almost)
    as full as the widest rows: title rows above it usually fill one cell.
    """

    scanned = rows[:HEADER_SCAN_ROWS]
    first_student = next((index for index, row in enumerate(scanned) if _is_student_row(row)), None)
    if first_student == 0:
        return 0
    if first_student is not None:
        header = first_student - 1
        while header > 0 and _is_weights_row(rows[header]):
            header -= 1
        if _filled(rows[header]) >= 2:
            return header
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
        names = [value for value in values if looks_like_name(value)]
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


def _grade_columns(rows: list[list[str]], header_row: int) -> set[int]:
    """Columns where most students below the header have a number."""

    students = [row for row in rows[header_row + 1 : header_row + 1 + HEADER_SCAN_ROWS] if _is_student_row(row)]
    if not students:
        return set()
    return {
        column
        for column in range(len(rows[0]))
        if sum(1 for row in students if parse_number(row[column]) is not None) * 2 > len(students)
    }


def detect_group_row(rows: list[list[str]], header_row: int) -> int | None:
    """The row above the header when it labels the activities.

    Activity labels sit above grade columns, so at least two of its cells must
    be over columns of numbers. A title split over two cells ("Curs 2025-26"
    and "Grup A") has at most one there and stays a title.
    """

    if header_row == 0 or not _is_group_row(rows[header_row - 1]):
        return None
    grade_columns = _grade_columns(rows, header_row)
    labelled = sum(1 for column, cell in enumerate(rows[header_row - 1]) if cell and column in grade_columns)
    return header_row - 1 if labelled >= 2 else None


def build_groups(rows: list[list[str]], header_row: int, group_row: int | None) -> list[ColumnGroup]:
    """Split the columns into activities.

    A group label spans the empty cells to its right as long as each column
    below it has its own, distinct label; a repeated label ("intent 1" again)
    starts a new, unlabelled group.
    """

    width = len(rows[0])
    sub = rows[header_row]
    if group_row is None:
        return [ColumnGroup(sub[column] or f"Columna {column_letter(column)}", [column], [""]) for column in range(width)]

    top = rows[group_row]
    groups: list[ColumnGroup] = []
    column = 0
    while column < width:
        span = [column]
        column += 1
        if sub[span[0]]:
            seen = {sub[span[0]].casefold()}
            while column < width and not top[column] and sub[column] and sub[column].casefold() not in seen:
                seen.add(sub[column].casefold())
                span.append(column)
                column += 1
        first = span[0]
        if len(span) == 1:
            label = " ".join(cell for cell in (top[first], sub[first]) if cell) or f"Columna {column_letter(first)}"
            groups.append(ColumnGroup(label, span, [""]))
        else:
            label = top[first] or GROUP_SEPARATOR.join(sub[index] for index in span)
            groups.append(ColumnGroup(label, span, [sub[index] for index in span]))
    return groups


def detect_identifier_columns(rows: list[list[str]], student_rows: list[int], skip: set[int]) -> list[int]:
    """Columns whose values identify students rather than grade them."""

    found = []
    for column in range(len(rows[0])):
        if column in skip:
            continue
        values = [rows[row][column] for row in student_rows if rows[row][column]]
        if not values:
            continue
        marked = sum(1 for value in values if DNI_PATTERN.match(value) or EMAIL_PATTERN.match(value) or "*" in value)
        keys = (
            len(values) >= 3
            and all(WHOLE_NUMBER_PATTERN.match(value) for value in values)
            and len(set(values)) == len(values)
            and max(int(value) for value in values) > 100
        )
        if keys or marked >= IDENTIFIER_SHARE * len(values):
            found.append(column)
    return found


def analyse_grades_sheet(
    rows: list[list[str]],
    header_row: int | None = None,
    name_column: int | None = None,
    grade_column: int | None = None,
    feedback_columns: list[int] | None = None,
    group_row: bool | None = None,
) -> GradesSheet:
    """Detect the sheet structure, honouring any choice the user already made."""

    if len(rows) < 2:
        raise ValueError(TOO_FEW_ROWS_MESSAGE)

    width = len(rows[0])
    if header_row is None or not 0 <= header_row < len(rows) - 1:
        header_row = detect_header_row(rows)
    # `group_row` says whether the row above the header labels the activities;
    # None detects it.
    if group_row is None:
        group_index = detect_group_row(rows, header_row)
    else:
        group_index = header_row - 1 if group_row and header_row > 0 else None
    top_row = header_row if group_index is None else group_index
    if name_column is None or not 0 <= name_column < width:
        name_column = detect_name_column(rows, header_row)
    # The final grade is the last column unless the user picks another one.
    if grade_column is None or not 0 <= grade_column < width:
        grade_column = width - 1

    student_rows = [
        index
        for index in range(header_row + 1, len(rows))
        if looks_like_name(rows[index][name_column])
    ]
    last_student = student_rows[-1] if student_rows else header_row
    # Rows after the last student without a name hold weights or maximums
    # ("50%", "10,00"). Percents become weights; the rest can be shown as a
    # footer.
    footer_rows = [
        index
        for index in range(last_student + 1, len(rows))
        if not looks_like_name(rows[index][name_column]) and _filled(rows[index]) > 0
    ]

    index_column = detect_index_column(rows, student_rows, name_column)
    identifier_columns = detect_identifier_columns(rows, student_rows, {name_column, grade_column})
    if feedback_columns is None:
        left_out = {name_column, index_column, *identifier_columns}
        feedback_columns = [column for column in range(width) if column not in left_out]
    else:
        feedback_columns = sorted({column for column in feedback_columns if 0 <= column < width})

    groups = build_groups(rows, header_row, group_index)
    columns = [""] * width
    for group in groups:
        for column, sub in zip(group.columns, group.subs):
            columns[column] = f"{group.label}{GROUP_SEPARATOR}{sub}" if sub else group.label
    weight_rows = [index for index in range(top_row) if _is_weights_row(rows[index])]
    title = GROUP_SEPARATOR.join(
        cell for index, row in enumerate(rows[:top_row]) if index not in weight_rows for cell in row if cell
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
        group_row=group_index,
        groups=groups,
        identifier_columns=identifier_columns,
    )
