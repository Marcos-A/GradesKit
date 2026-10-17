"""Fill tool: put final grades and feedback tables into a Moodle grading worksheet.

The flow is stateless. The browser sends the worksheet, the grades data and
the user's choices every time; `preview()` describes what would happen and
`fill()` returns the finished CSV. Nothing is stored on the server.
"""

import json
from dataclasses import dataclass, field

from gradeskit.feedback_html import LAYOUT_HORIZONTAL, LAYOUT_VERTICAL, render_feedback_table
from gradeskit.grades_sheet import GradesSheet, analyse_grades_sheet
from gradeskit.matching import STATUS_EXACT, STATUS_NONE, STATUS_PROBABLE, Person, match_people
from gradeskit.moodle_worksheet import (
    ROLE_EMAIL,
    ROLE_FEEDBACK,
    ROLE_FULLNAME,
    ROLE_GRADE,
    ROLE_IDENTIFIER,
    Worksheet,
    format_grade,
    write_worksheet,
)
from gradeskit.tabular import parse_number

# Statuses on top of the automatic ones from `gradeskit.matching`.
STATUS_CONFIRMED = "confirmed"
STATUS_MANUAL = "manual"
STATUS_EXCLUDED = "excluded"
APPLIED_STATUSES = {STATUS_EXACT, STATUS_CONFIRMED, STATUS_MANUAL}
NO_STUDENT = -1

NOTHING_TO_FILL_MESSAGE = "Cap participant té una nota assignada. Revisa la correspondència d'estudiants."
NO_FEEDBACK_COLUMN_WARNING = (
    "La tasca no té activats els «Comentaris de retroacció»: només s'ompliran les qualificacions."
)
EXISTING_GRADES_WARNING = (
    "{count} participants ja tenen una qualificació al Moodle. En pujar el fitxer, marca "
    "«Permet l'actualització de registres que s'hagin modificat més recentment a Moodle que al full "
    "de càlcul»; si no, el Moodle no les substituirà."
)


@dataclass
class FillOptions:
    header_row: int | None = None
    name_column: int | None = None
    grade_column: int | None = None
    feedback_columns: list[int] | None = None
    layout: str = LAYOUT_HORIZONTAL
    # Participant identifier -> grades sheet row chosen or confirmed by the
    # teacher, or NO_STUDENT to leave that participant untouched.
    matches: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_json(cls, text: str | None) -> "FillOptions":
        data = json.loads(text) if text else {}

        def optional_int(key: str) -> int | None:
            value = data.get(key)
            return int(value) if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit() else None

        feedback_columns = data.get("feedback_columns")
        return cls(
            header_row=optional_int("header_row"),
            name_column=optional_int("name_column"),
            grade_column=optional_int("grade_column"),
            feedback_columns=[int(value) for value in feedback_columns] if isinstance(feedback_columns, list) else None,
            layout=LAYOUT_VERTICAL if data.get("layout") == LAYOUT_VERTICAL else LAYOUT_HORIZONTAL,
            matches={str(key): int(value) for key, value in (data.get("matches") or {}).items()},
        )


@dataclass
class ParticipantPlan:
    row: int
    identifier: str
    fullname: str
    status: str
    student_row: int | None = None
    suggested_row: int | None = None
    grade_text: str = ""
    grade_value: str | None = None
    feedback: str | None = None
    replaces_grade: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        return self.status in APPLIED_STATUSES and self.student_row is not None

    def to_preview(self, sheet: GradesSheet) -> dict:
        return {
            "identifier": self.identifier,
            "fullname": self.fullname,
            "status": self.status,
            "student_row": self.student_row,
            "suggested_row": self.suggested_row,
            "student_name": sheet.student_name(self.student_row) if self.student_row is not None else "",
            "grade": self.grade_text,
            "applied": self.applied,
            "warnings": self.warnings,
        }


def load_grades_sheet(rows: list[list[str]], options: FillOptions) -> GradesSheet:
    return analyse_grades_sheet(
        rows,
        header_row=options.header_row,
        name_column=options.name_column,
        grade_column=options.grade_column,
        feedback_columns=options.feedback_columns,
    )


def student_feedback(sheet: GradesSheet, student_row: int, layout: str) -> str:
    columns = sheet.feedback_columns
    return render_feedback_table(
        headers=[sheet.columns[column] for column in columns],
        values=[sheet.rows[student_row][column] for column in columns],
        footer_rows=[[sheet.rows[row][column] for column in columns] for row in sheet.footer_rows],
        title=sheet.title,
        layout=layout,
    )


def plan_participants(
    worksheet: Worksheet, sheet: GradesSheet, options: FillOptions
) -> tuple[list[ParticipantPlan], list[int]]:
    """Decide, for each participant, which student row (if any) fills it.

    Returns the plans and the student rows that no participant uses.
    """

    participant_rows = worksheet.participant_rows()
    participants = [
        Person(key=row, name=worksheet.cell(row, ROLE_FULLNAME), email=worksheet.cell(row, ROLE_EMAIL))
        for row in participant_rows
    ]
    students = [Person(key=row, name=sheet.student_name(row)) for row in sheet.student_rows]
    automatic = match_people(participants, students)
    valid_students = set(sheet.student_rows)

    plans: list[ParticipantPlan] = []
    for row in participant_rows:
        match = automatic[row]
        plans.append(
            ParticipantPlan(
                row=row,
                identifier=worksheet.cell(row, ROLE_IDENTIFIER),
                fullname=worksheet.cell(row, ROLE_FULLNAME) or worksheet.cell(row, ROLE_EMAIL),
                status=match.status,
                student_row=match.candidate,
                suggested_row=match.candidate,
            )
        )

    # The teacher's choices win; a student they assign by hand is taken away
    # from any automatic match.
    taken_by_choice: set[int] = set()
    for plan in plans:
        choice = options.matches.get(plan.identifier)
        if choice is None:
            continue
        if choice == NO_STUDENT:
            plan.status, plan.student_row = STATUS_EXCLUDED, None
        elif choice in valid_students:
            plan.status = STATUS_CONFIRMED if choice == plan.suggested_row else STATUS_MANUAL
            plan.student_row = choice
            taken_by_choice.add(choice)
    for plan in plans:
        if plan.identifier not in options.matches and plan.student_row in taken_by_choice:
            plan.status, plan.student_row = STATUS_NONE, None

    max_grade = worksheet.max_grade()
    has_feedback = ROLE_FEEDBACK in worksheet.columns
    for plan in plans:
        if plan.student_row is None:
            continue
        plan.grade_text = sheet.rows[plan.student_row][sheet.grade_column]
        grade = parse_number(plan.grade_text)
        if grade is None:
            plan.warnings.append(f"La qualificació «{plan.grade_text}» no és numèrica: no s'importarà.")
        elif grade < 0 or (max_grade is not None and grade > max_grade):
            plan.warnings.append(
                f"La qualificació {plan.grade_text} és fora del rang permès (0–{format_grade(max_grade or 0, ',')}): "
                "el Moodle la ignoraria."
            )
        else:
            plan.grade_value = format_grade(grade, worksheet.decimal_separator)
        if not worksheet.grade_can_change(plan.row):
            plan.warnings.append("El Moodle indica que aquesta qualificació no es pot canviar.")
        existing = worksheet.cell(plan.row, ROLE_GRADE)
        plan.replaces_grade = existing not in ("", "-")
        if has_feedback:
            plan.feedback = student_feedback(sheet, plan.student_row, options.layout)

    used = {plan.student_row for plan in plans if plan.student_row is not None}
    unused = [row for row in sheet.student_rows if row not in used]
    return plans, unused


def preview(worksheet: Worksheet | None, grade_rows: list[list[str]] | None, options: FillOptions) -> dict:
    """Describe the worksheet, the grades sheet and the planned changes.

    Either input may be missing while the user is still filling the form; the
    response then describes only what is available.
    """

    result: dict = {
        "worksheet": worksheet.to_preview() if worksheet else None,
        "grades": None,
        "feedback_sample": None,
        "participants": [],
        "unused": [],
        "summary": None,
        "warnings": [],
    }
    if not grade_rows:
        return result

    sheet = load_grades_sheet(grade_rows, options)
    result["grades"] = sheet.to_preview()
    if sheet.student_rows:
        result["feedback_sample"] = student_feedback(sheet, sheet.student_rows[0], options.layout)
    if worksheet is None:
        return result

    plans, unused = plan_participants(worksheet, sheet, options)
    result["participants"] = [plan.to_preview(sheet) for plan in plans]
    result["unused"] = [{"row": row, "name": sheet.student_name(row)} for row in unused]
    applied = [plan for plan in plans if plan.applied]
    if applied:
        result["feedback_sample"] = applied[0].feedback or result["feedback_sample"]
    result["summary"] = {
        "participants": len(plans),
        "applied": len(applied),
        "pending": sum(1 for plan in plans if plan.status == STATUS_PROBABLE),
        "unmatched": sum(1 for plan in plans if plan.student_row is None),
    }
    if ROLE_FEEDBACK not in worksheet.columns:
        result["warnings"].append(NO_FEEDBACK_COLUMN_WARNING)
    replaced = sum(1 for plan in applied if plan.replaces_grade and plan.grade_value is not None)
    if replaced:
        result["warnings"].append(EXISTING_GRADES_WARNING.format(count=replaced))
    return result


def fill(worksheet: Worksheet, grade_rows: list[list[str]], options: FillOptions) -> bytes:
    """Return the worksheet CSV with grades and feedback for matched participants."""

    sheet = load_grades_sheet(grade_rows, options)
    plans, _ = plan_participants(worksheet, sheet, options)
    updates: dict[int, dict[str, str]] = {}
    for plan in plans:
        if not plan.applied:
            continue
        values = {}
        if plan.grade_value is not None:
            values[ROLE_GRADE] = plan.grade_value
        if plan.feedback is not None:
            values[ROLE_FEEDBACK] = plan.feedback
        if values:
            updates[plan.row] = values
    if not updates:
        raise ValueError(NOTHING_TO_FILL_MESSAGE)
    return write_worksheet(worksheet, updates)
