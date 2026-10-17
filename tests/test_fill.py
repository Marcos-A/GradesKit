"""Tests for the fill tool: grades sheet parsing, matching and worksheet output.

The fixtures copy the layout of a real Catalan grading worksheet and a
teacher's grades sheet (title row, weights footer row) with fictional students.
"""

import csv
import io
import json
import re
import unittest
from pathlib import Path

from gradeskit.feedback_html import (
    FAIL_STYLE,
    HEADER_STYLE,
    LAYOUT_VERTICAL,
    STRIPE_BACKGROUND,
    TITLE_STYLE,
    render_feedback_table,
)
from gradeskit.fill import NO_STUDENT, FillOptions, fill, preview
from gradeskit.grades_sheet import analyse_grades_sheet, format_weight
from gradeskit.matching import STATUS_EXACT, STATUS_NONE, STATUS_PROBABLE, Person, match_people
from gradeskit.moodle_worksheet import UNRECOGNIZED_WORKSHEET_MESSAGE, read_worksheet
from gradeskit.tabular import decode_text, parse_number, parse_table

FIXTURES = Path(__file__).parent / "fixtures"
WORKSHEET_BYTES = (FIXTURES / "worksheet_ca.csv").read_bytes()
GRADES_TEXT = (FIXTURES / "grades_paste.tsv").read_text(encoding="utf-8")


def unstyled(html: str) -> str:
    """Feedback HTML without the inline styles, to check its structure."""

    return re.sub(r' style="[^"]*"', "", html)


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

    def test_weights_come_from_percent_cells_only(self):
        sheet = analyse_grades_sheet(parse_table(GRADES_TEXT))
        self.assertEqual(sheet.detected_weights, {2: "50%", 3: "50%"})
        footer = sheet.footer_values([2, 3, 4, 5])
        self.assertEqual(footer, [["", "", "10,00", "10"]])

    def test_weights_row_above_header_stays_out_of_title(self):
        rows = parse_table("TOTAL A1\n\t40%\t60%\nNom\tActivitats\tExamen\nVidal Roca, Anna\t8\t9\n")
        sheet = analyse_grades_sheet(rows)
        self.assertEqual(sheet.title, "TOTAL A1")
        self.assertEqual(sheet.detected_weights, {1: "40%", 2: "60%"})

    def test_header_with_percent_is_not_given_a_weight(self):
        rows = parse_table("Nom\tExamen 50%\tTreball\nVidal Roca, Anna\t8\t9\n\t50%\t50%\n")
        self.assertEqual(analyse_grades_sheet(rows).detected_weights, {2: "50%"})

    def test_no_percents_means_no_weights(self):
        rows = parse_table("Nom\tExamen\nVidal Roca, Anna\t8\n\t10,00\n")
        self.assertEqual(analyse_grades_sheet(rows).detected_weights, {})

    def test_format_weight(self):
        self.assertEqual(format_weight("50"), "50%")
        self.assertEqual(format_weight("12,5 %"), "12,5%")
        self.assertEqual(format_weight("0,5"), "50%")
        with self.assertRaises(ValueError):
            format_weight("molt")

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
        html = unstyled(render_feedback_table(["<b>"], ["8"], [["50%"]], title="T & T"))
        self.assertIn("<th>&lt;b&gt;</th>", html)
        self.assertIn('<th colspan="1">T &amp; T</th>', html)
        self.assertIn("<tfoot><tr><td><small>50%</small></td></tr></tfoot>", html)
        self.assertNotIn("\n", html)

    def test_vertical_table_puts_weights_beside_values(self):
        html = render_feedback_table(["Examen"], ["8"], [["50%"]], layout=LAYOUT_VERTICAL)
        self.assertIn("<tr><th>Examen</th><td>8</td><td><small>50%</small></td></tr>", unstyled(html))

    def test_cells_are_centred_and_coloured(self):
        html = render_feedback_table(["Examen"], ["8"], [], title="A1")
        self.assertIn(f'<th colspan="1" style="{TITLE_STYLE}">A1</th>', html)
        self.assertIn(f'<th style="{HEADER_STYLE}">Examen</th>', html)
        self.assertIn('<td style="text-align:center;vertical-align:middle">8</td>', html)

    def test_numbers_under_five_and_np_are_red(self):
        html = render_feedback_table(["A", "B", "C", "D", "E"], ["4,99", "5", "NP", "0,00", "Apte"], [])
        cells = re.findall(r'<td style="([^"]*)">([^<]*)</td>', html)
        self.assertEqual([FAIL_STYLE in style for style, _ in cells], [True, False, True, True, False])
        self.assertNotIn("bold", "".join(style for style, _ in cells))

    def test_vertical_rows_are_striped(self):
        html = render_feedback_table(["A", "B", "C"], ["6", "7", "8"], [], layout=LAYOUT_VERTICAL)
        rows = re.findall(r"<tr>.*?</tr>", html)
        self.assertEqual([STRIPE_BACKGROUND in row for row in rows], [False, True, False])


class FillTests(unittest.TestCase):
    def test_matched_participants_get_grade_and_feedback(self):
        rows = filled_rows()
        sara = row_for(rows, "Participant1172192")
        self.assertEqual(sara[4], "9")
        self.assertIn("<td>8,69</td><td>10,00</td><td>9,34</td><td>9</td>", unstyled(sara[9]))
        self.assertIn("TOTAL A1 (1a convocatòria)", unstyled(sara[9]))
        self.assertIn("<th>Activitats (50%)</th><th>Examen (50%)</th><th>A1-TOTAL</th><th>A1</th>", unstyled(sara[9]))
        self.assertNotIn("<tfoot>", unstyled(sara[9]))
        self.assertNotIn("10,00</small>", unstyled(sara[9]))

    def test_footer_can_be_included_without_repeating_weights(self):
        sara = row_for(filled_rows(FillOptions(include_footer=True)), "Participant1172192")
        self.assertIn("<tfoot><tr><td><small></small></td><td><small></small></td><td><small>10,00</small></td>", unstyled(sara[9]))
        self.assertIn("<th>Examen (50%)</th>", unstyled(sara[9]))

    def test_teacher_weights_replace_detected_ones(self):
        rows = filled_rows(FillOptions(weights={2: "30", 3: "70 %", 4: "", 5: ""}))
        sara = row_for(rows, "Participant1172192")
        self.assertIn("<th>Activitats (30%)</th><th>Examen (70%)</th><th>A1-TOTAL</th>", unstyled(sara[9]))

    def test_invalid_weight_is_reported_and_left_out(self):
        worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
        result = preview(worksheet, parse_table(GRADES_TEXT), FillOptions(weights={2: "molt", 3: "50"}))
        self.assertEqual(result["grades"]["invalid_weights"], [2])
        self.assertEqual(result["grades"]["weights"], {"3": "50%"})
        self.assertIn("<th>Activitats</th><th>Examen (50%)</th>", unstyled(result["feedback_sample"]))

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
            json.dumps(
                {
                    "grade_column": "4",
                    "feedback_columns": [2, 3],
                    "layout": "vertical",
                    "weights": {"2": "40%", "3": ""},
                    "include_footer": True,
                    "matches": {"P1": -1},
                }
            )
        )
        self.assertEqual(options.grade_column, 4)
        self.assertEqual(options.feedback_columns, [2, 3])
        self.assertEqual(options.layout, LAYOUT_VERTICAL)
        self.assertEqual(options.weights, {2: "40%", 3: ""})
        self.assertTrue(options.include_footer)
        self.assertEqual(options.matches, {"P1": NO_STUDENT})
        self.assertIsNone(FillOptions.from_json("{}").weights)


if __name__ == "__main__":
    unittest.main()
