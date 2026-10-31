"""Add-grades tool: find each student's grade for the teacher's master list.

The master list has one row per student and any other columns (IDs, exercise
grades...). The grades list has a name and a grade per student, often with the
names written differently. The result has one row per master row after its header,
in the same order, with the student's name and grade or only the grade, as tab-separated
text ready to paste beside the master list in a spreadsheet.

The grade is taken from the column headed "Qualificacions" and the new
result has no header.

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

NO_NAME_COLUMN_MESSAGE = "No s'ha trobat cap columna amb noms d'estudiants a {part}."
MASTER_PART = "la llista principal"
GRADES_PART = "la llista de notes"
TOO_FEW_COLUMNS_MESSAGE = "La llista de notes ha de tenir com a mínim dues columnes: el nom i la nota."


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

    @classmethod
    def from_json(cls, text: str | None) -> "AddGradesOptions":
        data = json.loads(text) if text else {}

        def optional_int(key: str) -> int | None:
            value = data.get(key)
            return int(value) if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit() else None

        return cls(
            master_header_row=optional_int("master_header_row"),
            master_name_column=optional_int("master_name_column"),
            grades_header_row=optional_int("grades_header_row"),
            grades_name_column=optional_int("grades_name_column"),
            grades_grade_column=optional_int("grades_grade_column"),
            matches={int(key): int(value) for key, value in (data.get("matches") or {}).items()},
            output=OUTPUT_GRADE if data.get("output") == OUTPUT_GRADE else OUTPUT_NAME_AND_GRADE,
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
    if detect_header:
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


def default_grade_column(grades: StudentList) -> int:
    """The "Qualificacions" column; otherwise the last one with a value for
    some student, other than the names."""

    rows, student_rows, name_column = grades.rows, grades.student_rows, grades.name_column
    if grades.header_row != NO_HEADER:
        for column, header in enumerate(rows[grades.header_row]):
            if strip_accents(header).casefold().strip().startswith(GRADE_HEADER_PREFIX):
                return column
    for column in reversed(range(len(rows[0]))):
        if column != name_column and any(rows[row][column] for row in student_rows):
            return column
    return 0 if name_column else 1


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
    if grades:
        grade_column = options.grades_grade_column
        if grade_column is None or not 0 <= grade_column < len(grade_rows[0]):
            grade_column = default_grade_column(grades)
        result["grades"] = grades.to_preview() | {"grade_column": grade_column}
    if master is None or grades is None:
        return result

    # A student listed without a grade gets a 0, like one not listed at all.
    def grade_of(row: int) -> str:
        return with_decimal_comma(grades.rows[row][grade_column]) or MISSING_GRADE

    plans = plan_students(master, grades, options)
    by_row = {plan.row: plan for plan in plans}
    result["students"] = [
        {
            "row": plan.row,
            "name": plan.name,
            "status": plan.status,
            "grades_row": plan.grades_row,
            "grades_name": grades.name(plan.grades_row) if plan.grades_row is not None else "",
            "grade": grade_of(plan.grades_row) if plan.grades_row is not None else MISSING_GRADE,
            "alternatives": [grades.name(row) for row in plan.alternatives],
        }
        for plan in plans
    ]
    used = {plan.grades_row for plan in plans if plan.grades_row is not None}
    result["unused"] = [
        {"row": row, "name": grades.name(row), "grade": grade_of(row)} for row in grades.student_rows if row not in used
    ]
    result["summary"] = {
        "students": len(plans),
        "matched": len(used),
        "review": sum(1 for plan in plans if plan.status in (STATUS_PROBABLE, STATUS_AMBIGUOUS)),
        "missing": sum(1 for plan in plans if plan.grades_row is None),
    }

    # No header: the result starts after the master's header row and keeps
    # one row per master row from there, blank rows included, so it lines up
    # when pasted beside the first student. Empty rows at the end are dropped.
    first_row = master.header_row + 1
    output_rows = []
    for index, row in enumerate(master.rows[first_row:], start=first_row):
        grade = ""
        if index in by_row:
            plan = by_row[index]
            grade = grade_of(plan.grades_row) if plan.grades_row is not None else MISSING_GRADE
        output_rows.append([row[master.name_column], grade] if options.output == OUTPUT_NAME_AND_GRADE else [grade])
    while output_rows and not any(output_rows[-1]):
        output_rows.pop()
    result["output_rows"] = output_rows
    result["output_first_row"] = first_row
    result["text"] = rows_to_tsv(output_rows)
    return result

