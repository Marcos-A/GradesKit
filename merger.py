"""Core grade-merging logic shared by the web app, tests, and CLI wrapper.

This module is the "business rules" layer of the project: it knows how to
collect CSV files, read Moodle exports, combine attempts per student, and
serialize the final result back to CSV or XLSX.
"""

import csv
import io
import os
import unicodedata
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Iterable

# Moodle exports identify the relevant columns by localized header text rather
# than by fixed positions, so these markers are the contract between the parser
# and the CSV files it accepts.
EMAIL_COLUMN_MARKER = "Adreça electrònica"
NAME_COLUMN_MARKER = "Nom"
SURNAME_COLUMN_MARKER = "Cognoms"
GRADE_COLUMN_MARKER = "Qualificació"
RESULT_FILE_NAME = "result"
STRATEGY_HIGHEST = "highest"
STRATEGY_AVERAGE = "average"
STRATEGY_WEIGHTED = "weighted"
VALID_STRATEGIES = {STRATEGY_HIGHEST, STRATEGY_AVERAGE, STRATEGY_WEIGHTED}
FILE_NAME_SUFFIX = "-qualificacions.csv"


@dataclass
class InputFile:
    """Simple in-memory representation of an uploaded or extracted file."""

    name: str
    content: bytes


def strip_accents(value: str) -> str:
    """Normalize names for sorting so accents do not change the student order."""

    return "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def convert_grade_string_to_float(value: str) -> float:
    """Convert Moodle grade text to a number, treating blanks and "-" as zero."""

    cleaned = (value or "").strip()
    if cleaned in {"", "-"}:
        return 0.0
    return float(cleaned.replace(",", "."))


def format_grade_for_csv(value: float) -> str:
    """Write decimals using Moodle's comma-style formatting."""

    return f"{value:.2f}".replace(".", ",")


def normalize_percent(value: str | float | int | None, default: float = 0.8) -> float:
    """Accept user-friendly percentage inputs and convert them to a 0..1 ratio.

    The web app now treats the input field as a percentage, but the shared
    helper remains more flexible so the legacy CLI can still accept values such
    as ``0.8`` in addition to ``80`` or ``80%``.
    """

    if value is None:
        return default

    if isinstance(value, (int, float)):
        numeric = float(value)
        has_percent = False
    else:
        raw_value = str(value).strip().replace(" ", "")
        has_percent = "%" in raw_value
        cleaned = raw_value.replace("%", "").replace(",", ".")
        if not cleaned:
            return default
        numeric = float(cleaned)

    if numeric < 0:
        raise ValueError("El percentatge ponderat no pot ser negatiu.")
    if has_percent:
        if numeric <= 100:
            return numeric / 100
        raise ValueError("El percentatge ponderat ha d'estar entre 0 i 100.")
    if numeric <= 1:
        return numeric
    if numeric <= 100:
        return numeric / 100
    raise ValueError("El percentatge ponderat ha d'estar entre 0 i 1, o entre 0 i 100.")


def exercise_name_from_file_name(file_name: str) -> str:
    """Derive the exercise label from the Moodle export file name."""

    base_name = os.path.basename(file_name).replace("amp;", "&")
    if base_name.endswith(FILE_NAME_SUFFIX):
        return base_name[: -len(FILE_NAME_SUFFIX)]
    return os.path.splitext(base_name)[0]


def extract_input_files(
    uploaded_files: Iterable[InputFile],
    archive_file: InputFile | None = None,
) -> list[InputFile]:
    """Collect CSV files from direct uploads and, optionally, from one ZIP file.

    The browser sends every selected file through the same multipart field, so
    this helper decides whether each item is a plain CSV or a ZIP archive by
    looking at its filename extension.
    """

    extracted_files: list[InputFile] = []
    archive_candidates: list[InputFile] = []

    for uploaded_file in uploaded_files:
        lower_name = uploaded_file.name.lower()
        if lower_name.endswith(".csv"):
            extracted_files.append(
                InputFile(name=os.path.basename(uploaded_file.name), content=uploaded_file.content)
            )
        elif lower_name.endswith(".zip"):
            archive_candidates.append(uploaded_file)

    if archive_file is not None:
        archive_candidates.append(archive_file)

    for archive_file_candidate in archive_candidates:
        archive_name = archive_file_candidate.name.lower()
        if archive_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive_file_candidate.content)) as archive:
                for entry in archive.infolist():
                    if not entry.is_dir() and entry.filename.lower().endswith(".csv"):
                        extracted_files.append(
                            InputFile(
                                name=os.path.basename(entry.filename),
                                content=archive.read(entry),
                            )
                        )
        else:
            raise ValueError("Format d'arxiu no compatible. Puja un fitxer ZIP.")

    if not extracted_files:
        raise ValueError("No s'ha trobat cap fitxer CSV a la pujada.")

    return extracted_files


def _column_index(header: list[str], marker: str) -> int:
    """Find the first column whose header contains the requested Moodle label."""

    for index, column_name in enumerate(header):
        if marker in column_name:
            return index
    raise ValueError(f"No s'ha trobat cap columna que contingui '{marker}'.")


def _valid_grades(grades: list[float]) -> list[float]:
    """Ignore missing submissions and zero grades when aggregating attempts."""

    return [grade for grade in grades if grade > 0]


def compute_final_grade(strategy: str, grades: list[float], weighted_percent: float = 0.8) -> float:
    """Reduce one exercise's attempts to a single final grade.

    The weighted mode mirrors the original project rule: the best valid attempt
    gets the chosen percentage, and the remaining valid attempts split the rest
    evenly. Zero or missing attempts do not take part in the calculation.
    """

    valid_grades = _valid_grades(grades)
    if not valid_grades:
        return 0.0

    if strategy == STRATEGY_HIGHEST:
        return max(valid_grades)

    if strategy == STRATEGY_AVERAGE:
        return sum(valid_grades) / len(valid_grades)

    if strategy == STRATEGY_WEIGHTED:
        if len(valid_grades) == 1:
            return valid_grades[0]
        max_grade = max(valid_grades)
        remaining_grades = valid_grades.copy()
        # Remove only one instance of the highest grade. If the same top score
        # appears more than once, the additional occurrences still count as
        # "other attempts" and share the remaining percentage.
        remaining_grades.remove(max_grade)
        distributed_percent = (1 - weighted_percent) / len(remaining_grades)
        return (max_grade * weighted_percent) + sum(
            grade * distributed_percent for grade in remaining_grades
        )

    raise ValueError(f"Estratègia no compatible: '{strategy}'.")


def build_result_matrix(
    uploaded_files: Iterable[InputFile],
    strategy: str = STRATEGY_HIGHEST,
    weighted_percent: float = 0.8,
) -> list[list[str | float]]:
    """Build the tabular result used by both downloadable formats.

    The returned matrix has one of two shapes:

    - `highest`: one header row and one final grade column per exercise
    - `average` / `weighted`: a two-row header with attempt columns plus `total`

    Returning a neutral matrix here keeps CSV and XLSX generation simple: both
    serializers only need to turn rows into bytes.
    """

    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"Estratègia no compatible: '{strategy}'.")

    students: dict[str, dict[str, object]] = {}
    exercise_names: set[str] = set()
    max_attempts_per_exercise: dict[str, int] = {}

    for input_file in uploaded_files:
        exercise_name = exercise_name_from_file_name(input_file.name)
        exercise_names.add(exercise_name)

        content = input_file.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        try:
            header = next(reader)
        except StopIteration as error:
            raise ValueError(f"El fitxer '{input_file.name}' és buit.") from error

        email_column = _column_index(header, EMAIL_COLUMN_MARKER)
        name_column = _column_index(header, NAME_COLUMN_MARKER)
        surname_column = _column_index(header, SURNAME_COLUMN_MARKER)
        grade_column = _column_index(header, GRADE_COLUMN_MARKER)

        for row in reader:
            if not row:
                continue
            # Skip malformed rows instead of failing the whole upload. Moodle
            # exports occasionally include partial trailing rows.
            if max(email_column, name_column, surname_column, grade_column) >= len(row):
                continue

            student_email = row[email_column].strip()
            if not student_email:
                continue

            student = students.setdefault(
                student_email,
                {"name": "", "exercises": {}},
            )
            # The latest non-empty name seen for an email wins. This keeps the
            # output usable even if different CSVs vary slightly in formatting.
            student["name"] = f"{row[surname_column].strip()}, {row[name_column].strip()}".strip(", ")

            exercise_grades = student["exercises"].setdefault(exercise_name, [])
            exercise_grades.append(convert_grade_string_to_float(row[grade_column]))
            max_attempts_per_exercise[exercise_name] = max(
                max_attempts_per_exercise.get(exercise_name, 0),
                len(exercise_grades),
            )

    sorted_exercises = sorted(exercise_names)
    sorted_students = sorted(
        students.items(),
        key=lambda item: strip_accents(str(item[1]["name"])).lower(),
    )

    # Keep the output predictable: exercises are alphabetical and students are
    # sorted by name so repeated runs produce the same file structure.
    if strategy == STRATEGY_HIGHEST:
        rows: list[list[str | float]] = [["Nom", *sorted_exercises]]
        for _, student in sorted_students:
            exercise_results = []
            for exercise_name in sorted_exercises:
                grades = list(student["exercises"].get(exercise_name, []))
                final_grade = compute_final_grade(strategy, grades, weighted_percent)
                exercise_results.append(final_grade)
            rows.append([student["name"], *exercise_results])
        return rows

    # Average and weighted modes expose every attempt so the resulting file can
    # still be audited manually. The extra `total` column shows the value that
    # will actually count after applying the chosen strategy.
    header_row = ["Nom"]
    subheader_row = [""]
    for exercise_name in sorted_exercises:
        attempts = max_attempts_per_exercise.get(exercise_name, 1)
        header_row.append(exercise_name)
        subheader_row.append("intent 1")
        for attempt_number in range(2, attempts + 1):
            header_row.append("")
            subheader_row.append(f"intent {attempt_number}")
        header_row.append("")
        subheader_row.append("total")

    rows = [header_row, subheader_row]
    for _, student in sorted_students:
        student_row: list[str | float] = [student["name"]]
        for exercise_name in sorted_exercises:
            grades = list(student["exercises"].get(exercise_name, []))
            attempts = max_attempts_per_exercise.get(exercise_name, 1)
            padded_grades = grades + [0.0] * (attempts - len(grades))
            student_row.extend(padded_grades)
            student_row.append(compute_final_grade(strategy, grades, weighted_percent))
        rows.append(student_row)

    return rows


def rows_to_csv_bytes(rows: list[list[str | float]]) -> bytes:
    """Serialize the result matrix as a UTF-8 CSV download.

    The function does not need to know which strategy produced the rows; it
    simply writes whatever header shape `build_result_matrix()` returned.
    """

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(rows[0])
    for row in rows[1:]:
        writer.writerow(
            [
                format_grade_for_csv(value) if isinstance(value, float) else value
                for value in row
            ]
        )
    return output.getvalue().encode("utf-8")


def rows_to_xlsx_bytes(rows: list[list[str | float]]) -> bytes:
    """Serialize the result matrix as a minimal XLSX workbook.

    The project avoids third-party spreadsheet libraries so Docker builds can
    run without downloading Python packages. XLSX files are ZIP archives with a
    specific XML structure, so this function writes the smallest structure Excel
    and similar tools need in order to open the result cleanly.
    """

    output = io.BytesIO()

    worksheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_reference = _excel_cell_reference(row_index, column_index)
            if isinstance(value, float):
                # Style `1` uses Excel's standard numeric format with two
                # decimals, which keeps grades editable after download.
                cells.append(
                    f'<c r="{cell_reference}" s="1"><v>{value:.2f}</v></c>'
                )
            else:
                cells.append(
                    f'<c r="{cell_reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        worksheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        f'{"".join(worksheet_rows)}'
        "</sheetData>"
        "</worksheet>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            "<dc:title>MoodleGradesMerger</dc:title>"
            "</cp:coreProperties>",
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            "<Application>Python</Application>"
            "</Properties>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="result" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        archive.writestr("xl/styles.xml", styles_xml)

    return output.getvalue()


def merge_path_to_csv(
    input_path: str,
    output_path: str | None = None,
    strategy: str = STRATEGY_HIGHEST,
    weighted_percent: float = 0.8,
) -> str:
    """CLI helper: read all CSV files in a folder and write `result.csv`.

    This keeps the original repository workflow available even though the main
    product is now the web application.
    """

    path = Path(input_path)
    uploaded_files = [
        InputFile(name=file_path.name, content=file_path.read_bytes())
        for file_path in sorted(path.iterdir())
        if file_path.is_file() and file_path.suffix.lower() == ".csv"
    ]
    rows = build_result_matrix(
        uploaded_files=uploaded_files,
        strategy=strategy,
        weighted_percent=weighted_percent,
    )
    destination = output_path or str(path / f"{RESULT_FILE_NAME}.csv")
    Path(destination).write_bytes(rows_to_csv_bytes(rows))
    return destination


def _excel_cell_reference(row_index: int, column_index: int) -> str:
    """Convert numeric row/column positions to Excel-style references like C4."""

    column_label = []
    value = column_index
    while value:
        value, remainder = divmod(value - 1, 26)
        column_label.append(chr(65 + remainder))
    return f'{"".join(reversed(column_label))}{row_index}'
