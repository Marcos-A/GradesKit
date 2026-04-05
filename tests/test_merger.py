"""Focused regression tests for the core grade-merging rules.

These tests aim to protect the data-handling behavior that matters most:
strategy calculations, archive extraction, and output generation.
"""

import csv
import io
import unittest
import xml.etree.ElementTree as ET
import zipfile

from merger import (
    InputFile,
    STRATEGY_AVERAGE,
    STRATEGY_HIGHEST,
    STRATEGY_WEIGHTED,
    build_result_matrix,
    extract_input_files,
    normalize_percent,
    rows_to_csv_bytes,
    rows_to_xlsx_bytes,
)


FILE_ONE = """Adreça electrònica,Nom,Cognoms,Qualificació
alice@example.com,Alice,Zephyr,"7,0"
bob@example.com,Bob,Yard,"9,0"
"""

FILE_TWO = """Adreça electrònica,Nom,Cognoms,Qualificació
alice@example.com,Alice,Zephyr,"5,0"
bob@example.com,Bob,Yard,-
"""


class MergerTests(unittest.TestCase):
    def test_highest_strategy_uses_top_grade_for_repeated_attempts(self):
        """Repeated attempts in one exercise should collapse to the best score."""

        rows = build_result_matrix(
            uploaded_files=[
                InputFile(
                    name="exercise-qualificacions.csv",
                    content="""Adreça electrònica,Nom,Cognoms,Qualificació
alice@example.com,Alice,Zephyr,"7,0"
alice@example.com,Alice,Zephyr,"5,0"
bob@example.com,Bob,Yard,"9,0"
bob@example.com,Bob,Yard,-
""".encode(),
                )
            ],
            strategy=STRATEGY_HIGHEST,
        )
        self.assertEqual(rows[0], ["Nom", "exercise"])
        self.assertEqual(rows[1][0], "Yard, Bob")
        self.assertEqual(rows[1][1], 9.0)
        self.assertEqual(rows[2][1], 7.0)

    def test_average_strategy_ignores_missing_or_zero_attempts(self):
        """Average mode should only consider attempts that actually received a grade."""

        rows = build_result_matrix(
            uploaded_files=[
                InputFile(
                    name="exercise-qualificacions.csv",
                    content="""Adreça electrònica,Nom,Cognoms,Qualificació
alice@example.com,Alice,Zephyr,"8,0"
alice@example.com,Alice,Zephyr,-
alice@example.com,Alice,Zephyr,"4,0"
""".encode(),
                )
            ],
            strategy=STRATEGY_AVERAGE,
        )
        self.assertEqual(rows[0], ["Nom", "exercise", "", "", ""])
        self.assertEqual(rows[1], ["", "intent 1", "intent 2", "intent 3", "total"])
        self.assertEqual(rows[2][1:], [8.0, 0.0, 4.0, 6.0])

    def test_weighted_strategy_distributes_remaining_percent(self):
        """Weighted mode should favor the best attempt but still count the others."""

        rows = build_result_matrix(
            uploaded_files=[
                InputFile(
                    name="exercise-qualificacions.csv",
                    content="""Adreça electrònica,Nom,Cognoms,Qualificació
alice@example.com,Alice,Zephyr,"10,0"
alice@example.com,Alice,Zephyr,"6,0"
alice@example.com,Alice,Zephyr,"2,0"
""".encode(),
                )
            ],
            strategy=STRATEGY_WEIGHTED,
            weighted_percent=0.8,
        )
        self.assertEqual(rows[0], ["Nom", "exercise", "", "", ""])
        self.assertEqual(rows[1], ["", "intent 1", "intent 2", "intent 3", "total"])
        self.assertEqual(rows[2][1:], [10.0, 6.0, 2.0, 8.8])

    def test_single_attempt_still_shows_attempt_and_total_columns(self):
        """Single-attempt exercises should still expose the same table shape."""

        rows = build_result_matrix(
            uploaded_files=[
                InputFile(
                    name="exercise-qualificacions.csv",
                    content="""Adreça electrònica,Nom,Cognoms,Qualificació
alice@example.com,Alice,Zephyr,"7,5"
""".encode(),
                )
            ],
            strategy=STRATEGY_WEIGHTED,
            weighted_percent=0.8,
        )
        self.assertEqual(rows[0], ["Nom", "exercise", ""])
        self.assertEqual(rows[1], ["", "intent 1", "total"])
        self.assertEqual(rows[2], ["Zephyr, Alice", 7.5, 7.5])

    def test_percent_parser_accepts_common_formats(self):
        """People often type percentages differently in forms and scripts."""

        self.assertEqual(normalize_percent("80%"), 0.8)
        self.assertEqual(normalize_percent("80"), 0.8)
        self.assertEqual(normalize_percent("0.8"), 0.8)
        self.assertEqual(normalize_percent("0,8"), 0.8)

    def test_archive_extraction_reads_csv_files(self):
        """Compressed uploads should behave like direct CSV uploads."""

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("nested/exercise-qualificacions.csv", FILE_ONE)

        files = extract_input_files(
            uploaded_files=[],
            archive_file=InputFile(name="grades.zip", content=buffer.getvalue()),
        )

        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "exercise-qualificacions.csv")

    def test_csv_output_is_generated(self):
        """CSV output should keep the expected headers and student rows."""

        rows = build_result_matrix(
            uploaded_files=[
                InputFile(name="essay-qualificacions.csv", content=FILE_ONE.encode()),
                InputFile(name="project-qualificacions.csv", content=FILE_TWO.encode()),
            ],
            strategy=STRATEGY_HIGHEST,
        )
        csv_rows = list(csv.reader(io.StringIO(rows_to_csv_bytes(rows).decode("utf-8"))))
        self.assertEqual(csv_rows[0][0], "Nom")
        self.assertEqual(csv_rows[1][0], "Yard, Bob")

    def test_xlsx_output_is_generated(self):
        """XLSX export should produce a readable worksheet structure."""

        rows = build_result_matrix(
            uploaded_files=[
                InputFile(name="essay-qualificacions.csv", content=FILE_ONE.encode()),
            ],
            strategy=STRATEGY_HIGHEST,
        )
        xlsx_bytes = rows_to_xlsx_bytes(rows)
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as archive:
            worksheet = archive.read("xl/worksheets/sheet1.xml")
        root = ET.fromstring(worksheet)
        namespace = {"sheet": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows_xml = root.findall(".//sheet:row", namespace)
        self.assertEqual(len(rows_xml), 3)


if __name__ == "__main__":
    unittest.main()
