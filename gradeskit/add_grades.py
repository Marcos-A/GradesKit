"""Add-grades tool: find each student's grades for the teacher's master list.

The master list has one row per student and any other columns (IDs, exercise
grades...). The grades list has names and one or more grade columns. The result
has one row per master row after its header, in the same order, with the selected
grades and an optional student name. The tab-separated text has no header.

Like the fill tool, the flow is stateless: the browser sends both lists and
the teacher's choices every time and `preview()` returns everything.
"""

import json
from dataclasses import dataclass, field

from gradeskit.grades_sheet import detect_header_row, detect_name_column, looks_like_name
from gradeskit.matching import STATUS_NONE, STATUS_PROBABLE, Person, match_people, match_score, name_words
from gradeskit.tabular import column_letter, parse_number, strip_accents

STATUS_MANUAL = "manual"
STATUS_AMBIGUOUS = "ambiguous"
NO_HEADER = -1
NO_STUDENT = -1
MISSING_GRADE = "0"
# Matches "Qualificacions" and "Qualificació", with or without accents.
GRADE_HEADER_PREFIX = "qualificaci"
OUTPUT_NAME_AND_GRADE = "name_grade"
OUTPUT_GRADE = "grade"

# Moodle writes "-" for an assignment without a grade.
NO_GRADE_VALUES = ("", "-")

NO_NAME_COLUMN_MESSAGE = (
    "No s'ha trobat cap columna amb noms d'estudiants a {part}. "
    "Hi ha d'haver una columna amb el nom de cada estudiant, per exemple «Cognoms, Nom»."
)
MASTER_PART = "la llista principal"
GRADES_PART = "la llista de notes"
TOO_FEW_COLUMNS_MESSAGE = (
    "La llista de notes ha de tenir com a mínim dues columnes: el nom de l'estudiant i la nota, "
    "com el full de qualificacions del Moodle."
)
NOT_NAMES_WARNING = (
    "La llista principal no sembla tenir noms d'estudiants (nom i cognoms). "
    "Revisa-la o tria la columna dels noms a «Noms de la llista principal»."
)
NO_STUDENTS_WARNING = "No s'ha trobat cap estudiant a la llista principal."
NO_NUMERIC_GRADES_WARNING = (
    "La columna «{column}» de la llista de notes no té cap nota numèrica. "
    "Revisa la selecció a «Columnes de notes»."
)


@dataclass
class AddGradesOptions:
    # None lets the server detect each value; NO_HEADER means the list
    # starts with a student.
    master_header_row: int | None = None
    master_name_column: int | None = None
    grades_header_row: int | None = None
    grades_name_column: int | None = None
    grades_grade_column: int | None = None
    # Master row -> grades row chosen by the teacher, or NO_STUDENT for a 0.
    matches: dict[int, int] = field(default_factory=dict)
    output: str = OUTPUT_NAME_AND_GRADE
    # None detects a default; an empty list is an explicit empty selection.
    grades_grade_columns: list[int] | None = None

    @classmethod
    def from_json(cls, text: str | None) -> "AddGradesOptions":
        data = json.loads(text) if text else {}

        def optional_int(key: str) -> int | None:
            value = data.get(key)
            return int(value) if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit() else None

        columns = data.get("grades_grade_columns")
        if columns is not None and (
            not isinstance(columns, list) or any(type(column) is not int for column in columns)
        ):
            raise ValueError("Invalid grade column selection")

        return cls(
            master_header_row=optional_int("master_header_row"),
            master_name_column=optional_int("master_name_column"),
            grades_header_row=optional_int("grades_header_row"),
            grades_name_column=optional_int("grades_name_column"),
            grades_grade_column=optional_int("grades_grade_column"),
            matches={int(key): int(value) for key, value in (data.get("matches") or {}).items()},
            output=OUTPUT_GRADE if data.get("output") == OUTPUT_GRADE else OUTPUT_NAME_AND_GRADE,
            grades_grade_columns=columns,
        )


@dataclass
class StudentList:
    rows: list[list[str]]
    header_row: int
    columns: list[str]
    name_column: int
    student_rows: list[int]

    def name(self, row: int) -> str:
        return self.rows[row][self.name_column]

    def to_preview(self) -> dict:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "header_row": self.header_row,
            "name_column": self.name_column,
            "student_rows": self.student_rows,
        }


def detect_list_header(rows: list[list[str]]) -> int:
    """Header row of a student list, or NO_HEADER when it starts with a student.

    Headers hold labels, so a row with a number in it is already a student:
    the header, if any, is the row above it.
    """

    index = detect_header_row(rows) if len(rows) > 1 else 0
    if any(parse_number(cell) is not None for cell in rows[index]):
        return index - 1
    return index


def has_full_names(values: list[str]) -> bool:
    """Whether most non-empty values have at least a name and a surname."""

    names = [value for value in values if value]
    return sum(1 for name in names if len(name_words(name)) >= 2) * 2 >= len(names)


def analyse_list(rows: list[list[str]], header_row: int | None, name_column: int | None, part: str) -> StudentList:
    width = len(rows[0])
    detect_header = header_row is None or not NO_HEADER <= header_row < len(rows)
    if detect_header:
        header_row = detect_list_header(rows)
    if name_column is None or not 0 <= name_column < width:
        try:
            name_column = detect_name_column(rows, header_row)
        except ValueError as error:
            raise ValueError(NO_NAME_COLUMN_MESSAGE.format(part=part)) from error
    if detect_header and has_full_names([row[name_column] for row in rows[header_row + 1 :]]):
        # Students have a name and a surname, so a one-word name cell ("Nom")
        # right after the detected header is the real header; one-column
        # lists with a title row ("Grup 1A") need this.
        while header_row + 2 < len(rows) and len(name_words(rows[header_row + 1][name_column])) == 1:
            header_row += 1
    header = rows[header_row] if header_row != NO_HEADER else [""] * width
    return StudentList(
        rows=rows,
        header_row=header_row,
        columns=[header[column] or f"Columna {column_letter(column)}" for column in range(width)],
        name_column=name_column,
        student_rows=[
            index for index in range(header_row + 1, len(rows)) if looks_like_name(rows[index][name_column])
        ],
    )


def header_is_student(names: StudentList, other: StudentList) -> bool:
    """Whether the detected header row of `names` is a student of `other`.

    A list without a header whose first row has no numbers looks like it
    starts with a header; if that "header" matches a student of the other
    list, it is a student. Students have at least a name and a surname, so
    one-word headers such as "Nom" never count, even if both lists use them.
    """

    if names.header_row == NO_HEADER:
        return False
    header = Person(key=-1, name=names.name(names.header_row))
    if len(name_words(header.name)) < 2:
        return False
    return any(match_score(header, Person(key=row, name=other.name(row))) > 0 for row in other.student_rows)


def master_warnings(master: StudentList) -> list[str]:
    """Warn when the main list does not look like a list of students.

    Students have a name and a surname, so a name column where most values
    are a single word (IDs, groups, first names only) is probably not one.
    """

    names = [master.name(row) for row in master.student_rows]
    if not names:
        return [NO_STUDENTS_WARNING]
    if not has_full_names(names):
        return [NOT_NAMES_WARNING]
    return []


def default_grade_column(grades: StudentList) -> int:
    """The "Qualificacions" column; otherwise the last one with a value for
    some student, other than the names."""

    rows, student_rows, name_column = grades.rows, grades.student_rows, grades.name_column
    if grades.header_row != NO_HEADER:
        for column, header in enumerate(rows[grades.header_row]):
            if column != name_column and strip_accents(header).casefold().strip().startswith(GRADE_HEADER_PREFIX):
                return column
    for column in reversed(range(len(rows[0]))):
        if column != name_column and any(rows[row][column] for row in student_rows):
            return column
    return 0 if name_column else 1


def selected_grade_columns(grades: StudentList, options: AddGradesOptions) -> list[int]:
    if options.grades_grade_columns is None:
        column = options.grades_grade_column
        if column is not None and 0 <= column < len(grades.columns):
            return [column]
        return [default_grade_column(grades)]
    return sorted({
        column for column in options.grades_grade_columns
        if 0 <= column < len(grades.columns) and column != grades.name_column
    })


@dataclass
class StudentPlan:
    row: int
    name: str
    status: str
    grades_row: int | None = None
    alternatives: list[int] = field(default_factory=list)


def plan_students(master: StudentList, grades: StudentList, options: AddGradesOptions) -> list[StudentPlan]:
    automatic = match_people(
        [Person(key=row, name=master.name(row)) for row in master.student_rows],
        [Person(key=row, name=grades.name(row)) for row in grades.student_rows],
    )
    plans = []
    for row in master.student_rows:
        match = automatic[row]
        status = match.status
        if status == STATUS_NONE and match.alternatives:
            status = STATUS_AMBIGUOUS
        plans.append(
            StudentPlan(row=row, name=master.name(row), status=status, grades_row=match.candidate, alternatives=match.alternatives)
        )

    # The teacher's choices win; a grades row they assign by hand is taken
    # away from any automatic match.
    valid = set(grades.student_rows)
    taken_by_choice: set[int] = set()
    for plan in plans:
        choice = options.matches.get(plan.row)
        if choice == NO_STUDENT:
            plan.status, plan.grades_row = STATUS_MANUAL, None
        elif choice in valid:
            plan.status, plan.grades_row = STATUS_MANUAL, choice
            taken_by_choice.add(choice)
    for plan in plans:
        if plan.row not in options.matches and plan.grades_row in taken_by_choice:
            plan.status, plan.grades_row = STATUS_NONE, None
    return plans


def with_decimal_comma(value: str) -> str:
    """Write a number with a decimal comma ("7.25" -> "7,25"); text such as
    "NP" and numbers already written with a comma are left as they are."""

    if "." not in value or parse_number(value) is None:
        return value
    if "," in value:
        if value.rfind(",") > value.rfind("."):
            return value  # "1.234,5": the comma is already the decimal one.
        value = value.replace(",", "")  # "1,234.5": the comma groups thousands.
    return value.replace(".", ",")


def rows_to_tsv(rows: list[list[str]]) -> str:
    """Tab-separated text as spreadsheets put it on the clipboard.

    Only cells with a tab, a line break or a leading quote are quoted; the
    csv module would write a lone empty cell as `""`, which some spreadsheets
    paste literally.
    """

    def cell(value: str) -> str:
        if any(char in value for char in "\t\r\n") or value.startswith('"'):
            return '"' + value.replace('"', '""') + '"'
        return value

    return "".join("\t".join(cell(value) for value in row) + "\n" for row in rows)


def preview(master_rows: list[list[str]] | None, grade_rows: list[list[str]] | None, options: AddGradesOptions) -> dict:
    """Describe both lists, the matching and the resulting table.

    Either list may be missing while the teacher is still filling the form.
    """

    result: dict = {
        "master": None,
        "grades": None,
        "students": [],
        "unused": [],
        "summary": None,
        "output_rows": [],
        "output_first_row": 0,
        "text": "",
        "warnings": [],
    }
    master = grades = None
    if master_rows:
        master = analyse_list(master_rows, options.master_header_row, options.master_name_column, MASTER_PART)
    if grade_rows:
        if len(grade_rows[0]) < 2:
            raise ValueError(TOO_FEW_COLUMNS_MESSAGE)
        grades = analyse_list(grade_rows, options.grades_header_row, options.grades_name_column, GRADES_PART)
    # A detected header that is really a student moves up, as in
    # `detect_list_header`. Headers chosen by the teacher are kept.
    if master and grades:
        if options.master_header_row is None and header_is_student(master, grades):
            master = analyse_list(master_rows, master.header_row - 1, options.master_name_column, MASTER_PART)
        if options.grades_header_row is None and header_is_student(grades, master):
            grades = analyse_list(grade_rows, grades.header_row - 1, options.grades_name_column, GRADES_PART)
    if master:
        result["master"] = master.to_preview()
        result["warnings"] += master_warnings(master)
    if grades:
        grade_columns = selected_grade_columns(grades, options)
        result["grades"] = grades.to_preview() | {
            "grade_columns": grade_columns,
            "grade_column": grade_columns[0] if grade_columns else None,
        }
        for column in grade_columns:
            values = [grades.rows[row][column] for row in grades.student_rows]
            if any(value not in NO_GRADE_VALUES for value in values) and not any(parse_number(value) is not None for value in values):
                result["warnings"].append(NO_NUMERIC_GRADES_WARNING.format(column=grades.columns[column]))
    if master is None or grades is None:
        return result

    def grades_of(row: int | None) -> list[str]:
        if row is None:
            return [MISSING_GRADE] * len(grade_columns)
        values = (grades.rows[row][column] for column in grade_columns)
        return [MISSING_GRADE if value in NO_GRADE_VALUES else with_decimal_comma(value) for value in values]

    plans = plan_students(master, grades, options)
    grades_by_row = {}
    for plan in plans:
        values = grades_of(plan.grades_row)
        grades_by_row[plan.row] = values
        result["students"].append({
            "row": plan.row,
            "name": plan.name,
            "status": plan.status,
            "grades_row": plan.grades_row,
            "grades_name": grades.name(plan.grades_row) if plan.grades_row is not None else "",
            "grades": values,
            "grade": values[0] if values else "",
            "alternatives": [grades.name(row) for row in plan.alternatives],
        })
    used = {plan.grades_row for plan in plans if plan.grades_row is not None}
    for row in grades.student_rows:
        if row not in used:
            values = grades_of(row)
            result["unused"].append({
                "row": row,
                "name": grades.name(row),
                "grades": values,
                "grade": values[0] if values else "",
            })
    result["summary"] = {
        "students": len(plans),
        "matched": len(used),
        "review": sum(1 for plan in plans if plan.status in (STATUS_PROBABLE, STATUS_AMBIGUOUS)),
        "missing": sum(1 for plan in plans if plan.grades_row is None),
    }
    if not grade_columns:
        return result

    # No header: the result starts after the master's header row and keeps
    # one row per master row from there, blank rows included, so it lines up
    # when pasted beside the first student. Empty rows at the end are dropped.
    first_row = master.header_row + 1
    blank_grades = [""] * len(grade_columns)
    output_rows = []
    for index, row in enumerate(master.rows[first_row:], start=first_row):
        values = grades_by_row.get(index, blank_grades)
        output_rows.append([row[master.name_column], *values] if options.output == OUTPUT_NAME_AND_GRADE else values)
    while output_rows and not any(output_rows[-1]):
        output_rows.pop()
    result["output_rows"] = output_rows
    result["output_first_row"] = first_row
    result["text"] = rows_to_tsv(output_rows)
    return result

