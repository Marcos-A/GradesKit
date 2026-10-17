"""Tests for the fill tool: grades sheet parsing, matching and worksheet output.

The fixtures copy the layout of a real Catalan grading worksheet and a
teacher's grades sheet (title row, weights footer row) with fictional students.
"""

import csv
import io
import json
import unittest
from pathlib import Path

from gradeskit.feedback_html import LAYOUT_VERTICAL, render_feedback_table
from gradeskit.fill import NO_STUDENT, FillOptions, fill, preview
from gradeskit.grades_sheet import analyse_grades_sheet
from gradeskit.matching import STATUS_EXACT, STATUS_NONE, STATUS_PROBABLE, Person, match_people
from gradeskit.moodle_worksheet import UNRECOGNIZED_WORKSHEET_MESSAGE, read_worksheet
from gradeskit.tabular import decode_text, parse_number, parse_table

FIXTURES = Path(__file__).parent / "fixtures"
WORKSHEET_BYTES = (FIXTURES / "worksheet_ca.csv").read_bytes()
GRADES_TEXT = (FIXTURES / "grades_paste.tsv").read_text(encoding="utf-8")


def filled_rows(options: FillOptions | None = None) -> list[list[str]]:
    worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
    output = fill(worksheet, parse_table(GRADES_TEXT), options or FillOptions())
    return list(csv.reader(io.StringIO(output.decode("utf-8"))))


def row_for(rows: list[list[str]], identifier: str) -> list[str]:
    return next(row for row in rows if row[0] == identifier)


class TabularTests(unittest.TestCase):
    def test_paste_uses_tabs_and_drops_empty_columns(self):
        rows = parse_table("a\t\tb\n1\t\t2,5\n")
        self.assertEqual(rows, [["a", "b"], ["1", "2,5"]])

    def test_semicolon_csv_with_decimal_commas(self):
        rows = parse_table("Nom;Nota\nAna;7,5\nBea;8\n")
        self.assertEqual(rows, [["Nom", "Nota"], ["Ana", "7,5"], ["Bea", "8"]])

    def test_windows_1252_fallback(self):
        self.assertEqual(decode_text("Qualificació".encode("cp1252")), "Qualificació")

    def test_parse_number(self):
        self.assertEqual(parse_number("7,86"), 7.86)
        self.assertEqual(parse_number("1.234,5"), 1234.5)
        self.assertIsNone(parse_number("NP"))


class GradesSheetTests(unittest.TestCase):
    def test_detects_title_header_students_and_footer(self):
        sheet = analyse_grades_sheet(parse_table(GRADES_TEXT))
        self.assertEqual(sheet.title, "TOTAL A1 (1a convocatòria)")
        self.assertEqual(sheet.columns, ["#", "ESTUDIANT", "Activitats", "Examen", "A1-TOTAL", "A1"])
        self.assertEqual(sheet.name_column, 1)
        self.assertEqual(sheet.index_column, 0)
        self.assertEqual(len(sheet.student_rows), 9)
        self.assertEqual(sheet.rows[sheet.footer_rows[0]][2], "50%")

    def test_grade_defaults_to_last_column_and_can_be_overridden(self):
        rows = parse_table(GRADES_TEXT)
        self.assertEqual(analyse_grades_sheet(rows).grade_column, 5)
        self.assertEqual(analyse_grades_sheet(rows, grade_column=4).grade_column, 4)

    def test_feedback_leaves_out_counter_and_name_columns(self):
        sheet = analyse_grades_sheet(parse_table(GRADES_TEXT))
        self.assertEqual(sheet.feedback_columns, [2, 3, 4, 5])


class MatchingTests(unittest.TestCase):
    def test_reordered_names_with_different_accents_match_exactly(self):
        matches = match_people(
            [Person(1, "Ines Bonet Prat")],
            [Person(10, "Bonet Prat, Inés")],
        )
        self.assertEqual(matches[1].status, STATUS_EXACT)
        self.assertEqual(matches[1].candidate, 10)

    def test_missing_second_surname_is_probable(self):
        matches = match_people([Person(1, "Arjun Patel")], [Person(10, "Patel Shah, Arjun")])
        self.assertEqual(matches[1].status, STATUS_PROBABLE)

    def test_ambiguous_candidates_are_left_for_the_teacher(self):
        matches = match_people(
            [Person(1, "Anna Vidal")],
            [Person(10, "Vidal Roca, Anna"), Person(11, "Vidal Rius, Anna")],
        )
        self.assertEqual(matches[1].status, STATUS_NONE)
        self.assertEqual(sorted(matches[1].alternatives), [10, 11])

    def test_email_wins_over_names(self):
        matches = match_people(
            [Person(1, "Sara M.", email="sara@example.com")],
            [Person(10, "Someone Else", email="SARA@example.com")],
        )
        self.assertEqual(matches[1].candidate, 10)


class WorksheetTests(unittest.TestCase):
    def test_reads_catalan_worksheet(self):
        worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
        summary = worksheet.to_preview()
        self.assertEqual(summary["language"], "ca")
        self.assertEqual(summary["participants"], 10)
        self.assertEqual(summary["feedback_header"], "Comentaris de retroacció.")
        self.assertEqual(summary["max_grade"], 10.0)

    def test_reads_english_worksheet(self):
        content = (
            "Identifier,Full name,Email address,Status,Grade,Maximum grade,Grade can be changed,"
            "Last modified (submission),Last modified (grade),Feedback comments\n"
            "Participant 1,Ana Zeta,ana@example.com,Submitted,,100.00,Yes,-,-,\n"
        ).encode()
        worksheet = read_worksheet(content, "worksheet.csv")
        self.assertEqual(worksheet.language, "en")
        self.assertEqual(worksheet.decimal_separator, ".")

    def test_rejects_other_files(self):
        with self.assertRaisesRegex(ValueError, UNRECOGNIZED_WORKSHEET_MESSAGE):
            read_worksheet(b"a,b\n1,2\n", "other.csv")


class FeedbackTests(unittest.TestCase):
    def test_horizontal_table_escapes_values(self):
        html = render_feedback_table(["<b>"], ["8"], [["50%"]], title="T & T")
        self.assertIn("<th>&lt;b&gt;</th>", html)
        self.assertIn('<th colspan="1">T &amp; T</th>', html)
        self.assertIn("<tfoot><tr><td><small>50%</small></td></tr></tfoot>", html)
        self.assertNotIn("\n", html)

    def test_vertical_table_puts_weights_beside_values(self):
        html = render_feedback_table(["Examen"], ["8"], [["50%"]], layout=LAYOUT_VERTICAL)
        self.assertIn("<tr><th>Examen</th><td>8</td><td><small>50%</small></td></tr>", html)


class FillTests(unittest.TestCase):
    def test_matched_participants_get_grade_and_feedback(self):
        rows = filled_rows()
        sara = row_for(rows, "Participant1172192")
        self.assertEqual(sara[4], "9")
        self.assertIn("<td>8,69</td><td>10,00</td><td>9,34</td><td>9</td>", sara[9])
        self.assertIn("TOTAL A1 (1a convocatòria)", sara[9])
        self.assertIn("<small>50%</small>", sara[9])

    def test_header_and_unmatched_rows_are_untouched(self):
        original = list(csv.reader(io.StringIO(WORKSHEET_BYTES.decode("utf-8"))))
        rows = filled_rows()
        self.assertEqual(rows[0], original[0])
        self.assertEqual(row_for(rows, "Participant1172217"), row_for(original, "Participant1172217"))

    def test_probable_matches_wait_for_confirmation(self):
        worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
        grades = parse_table(GRADES_TEXT + "10\tPatel Shah, Arjun\t7\t7\t7\t7\n")
        result = preview(worksheet, grades, FillOptions())
        arjun = next(p for p in result["participants"] if p["identifier"] == "Participant1172202")
        self.assertEqual(arjun["status"], STATUS_PROBABLE)
        self.assertFalse(arjun["applied"])

        options = FillOptions(matches={"Participant1172202": arjun["student_row"]})
        output = fill(worksheet, grades, options).decode("utf-8")
        filled = row_for(list(csv.reader(io.StringIO(output))), "Participant1172202")
        self.assertEqual(filled[4], "7")

    def test_manual_choice_and_exclusion(self):
        sheet = analyse_grades_sheet(parse_table(GRADES_TEXT))
        hugo_row = next(row for row in sheet.student_rows if sheet.student_name(row) == "Romero, Hugo")
        rows = filled_rows(
            FillOptions(matches={"Participant1172217": hugo_row, "Participant1172192": NO_STUDENT})
        )
        self.assertEqual(row_for(rows, "Participant1172217")[4], "9")
        self.assertEqual(row_for(rows, "Participant1172192")[4], "")

    def test_out_of_range_grade_is_not_written(self):
        worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
        grades = parse_table("Nom\tNota\nVidal Roca, Anna\t12\n")
        result = preview(worksheet, grades, FillOptions())
        sara = next(p for p in result["participants"] if p["identifier"] == "Participant1172192")
        self.assertTrue(sara["warnings"])
        output = fill(worksheet, grades, FillOptions()).decode("utf-8")
        self.assertEqual(row_for(list(csv.reader(io.StringIO(output))), "Participant1172192")[4], "")

    def test_options_round_trip_from_json(self):
        options = FillOptions.from_json(
            json.dumps({"grade_column": "4", "feedback_columns": [2, 3], "layout": "vertical", "matches": {"P1": -1}})
        )
        self.assertEqual(options.grade_column, 4)
        self.assertEqual(options.feedback_columns, [2, 3])
        self.assertEqual(options.layout, LAYOUT_VERTICAL)
        self.assertEqual(options.matches, {"P1": NO_STUDENT})


if __name__ == "__main__":
    unittest.main()
