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
    RESULT_STYLE,
    HEADER_STYLE,
    ROW_HEADER_STYLE,
    LAYOUT_HORIZONTAL,
    LAYOUT_VERTICAL,
    STRIPE_BACKGROUND,
    TITLE_STYLE,
    FeedbackEntry,
    FeedbackGroup,
    render_feedback_table,
    render_grouped_table,
)
from gradeskit.fill import NO_STUDENT, FillOptions, fill, preview, student_feedback
from gradeskit.grades_sheet import analyse_grades_sheet, detect_header_row, format_weight
from gradeskit.matching import STATUS_EXACT, STATUS_NONE, STATUS_PROBABLE, Person, match_people
from gradeskit.moodle_worksheet import UNRECOGNIZED_WORKSHEET_MESSAGE, read_worksheet
from gradeskit.tabular import decode_text, parse_number, parse_table

FIXTURES = Path(__file__).parent / "fixtures"
WORKSHEET_BYTES = (FIXTURES / "worksheet_ca.csv").read_bytes()
GRADES_TEXT = (FIXTURES / "grades_paste.tsv").read_text(encoding="utf-8")

# A two-row header: activity labels merged over their columns, then each
# column's own label. Identifier columns sit before the grades.
TWO_ROW_TEXT = (
    "ESTUDIANT\tCLAU\tDNI/NIE\tID PUBLICABLE\tConceptes 01\t\t\tConceptes 02\t\t\tTOTAL\n"
    "\t\t\t\tintent 1\tintent 2\ttotal\tintent 1\tintent 2\ttotal\t\n"
    "Costa Pons, Oriol\t5987\t12345678Z\t****5678Z\t6,00\t7,00\t6,80\t5,56\t6,67\t6,45\t6,63\n"
    "Mir Sala, Berta\t619\tY1234567X\t****4567X\t9,00\t0,00\t9,00\t10,00\t0,00\t10,00\t9,50\n"
    "Serra Viñals, Julia\t179\tX7654321L\t****4321L\t8,00\t9,00\t8,80\t4,44\t10,00\t8,89\t8,85\n"
    "\t\t\t\t\t\t50%\t\t\t50%\t10,00\n"
)

# Activities with two and three attempts, a single-column activity named
# across both header rows, and weights in footer cells merged from the
# activity's first column.
MIXED_TEXT = (
    "ESTUDIANT\tCorreu\tConceptes 01\t\t\tPràctica 02\t\t\t\tProjecte\tExamen\tTOTAL\n"
    "\t\tintent 1\tintent 2\ttotal\tintent 1\tintent 2\tintent 3\ttotal\tfinal\t\t\n"
    "Costa Pons, Oriol\toriol@example.com\t6,00\t7,00\t6,80\t4,00\t6,00\t8,00\t8,00\t7,50\t6,25\t7,20\n"
    "Mir Sala, Berta\tberta@example.com\t7,00\t9,00\t8,60\t9,00\t0,00\t0,00\t9,00\t8,00\t9,10\t8,70\n"
    "\t\t25%\t\t\t25%\t\t\t\t25%\t25%\t10,00\n"
)


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

    def test_vertical_row_headers_are_left_aligned(self):
        html = render_feedback_table(["Examen"], ["8"], [], title="A1", layout=LAYOUT_VERTICAL)
        self.assertIn(f'<th style="{ROW_HEADER_STYLE}">Examen</th>', html)
        self.assertIn("text-align:left", ROW_HEADER_STYLE)
        self.assertIn(f'<th colspan="2" style="{TITLE_STYLE}">A1</th>', html)
        self.assertIn('<td style="text-align:center;vertical-align:middle">8</td>', html)

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
                    "group_row": True,
                    "feedback_columns": [2, 3],
                    "layout": "vertical",
                    "weights": {"2": "40%", "3": ""},
                    "include_footer": True,
                    "matches": {"P1": -1},
                }
            )
        )
        self.assertEqual(options.grade_column, 4)
        self.assertTrue(options.group_row)
        self.assertIsNone(FillOptions.from_json("{}").group_row)
        self.assertEqual(options.feedback_columns, [2, 3])
        self.assertEqual(options.layout, LAYOUT_VERTICAL)
        self.assertEqual(options.weights, {2: "40%", 3: ""})
        self.assertTrue(options.include_footer)
        self.assertEqual(options.matches, {"P1": NO_STUDENT})
        self.assertIsNone(FillOptions.from_json("{}").weights)


class GroupedSheetTests(unittest.TestCase):
    def test_two_row_header_groups_attempts_under_each_activity(self):
        sheet = analyse_grades_sheet(parse_table(TWO_ROW_TEXT))
        self.assertEqual((sheet.group_row, sheet.header_row), (0, 1))
        self.assertEqual(sheet.title, "")
        self.assertTrue(sheet.grouped)
        self.assertEqual(
            [(group.label, group.columns, group.subs) for group in sheet.groups[4:]],
            [
                ("Conceptes 01", [4, 5, 6], ["intent 1", "intent 2", "total"]),
                ("Conceptes 02", [7, 8, 9], ["intent 1", "intent 2", "total"]),
                ("TOTAL", [10], [""]),
            ],
        )
        self.assertEqual(sheet.columns[0], "ESTUDIANT")
        self.assertEqual(sheet.columns[5], "Conceptes 01 · intent 2")
        self.assertEqual(sheet.student_rows, [2, 3, 4])
        self.assertEqual(sheet.detected_weights, {6: "50%", 9: "50%"})

    def test_attempt_counts_vary_and_single_columns_join_both_header_cells(self):
        sheet = analyse_grades_sheet(parse_table(MIXED_TEXT))
        groups = {group.label: group for group in sheet.groups}
        self.assertEqual(groups["Pràctica 02"].subs, ["intent 1", "intent 2", "intent 3", "total"])
        self.assertEqual(groups["Projecte final"].columns, [9])
        self.assertEqual(groups["Examen"].columns, [10])
        self.assertEqual(groups["TOTAL"].columns, [11])

    def test_weight_under_the_first_column_belongs_to_the_activity(self):
        worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
        result = preview(worksheet, parse_table(MIXED_TEXT), FillOptions())
        self.assertIn("Conceptes 01 (25%)", result["feedback_sample"])
        self.assertIn("Pràctica 02 (25%)", result["feedback_sample"])

    def test_flat_sheet_has_no_group_row(self):
        sheet = analyse_grades_sheet(parse_table(GRADES_TEXT))
        self.assertEqual((sheet.header_row, sheet.group_row), (1, None))
        self.assertFalse(sheet.grouped)

    def test_single_cell_title_row_is_not_a_group_row(self):
        sheet = analyse_grades_sheet(parse_table("Notes finals\nNom\tExamen\tTreball\nVidal Roca, Anna\t8\t9\n"))
        self.assertEqual((sheet.header_row, sheet.group_row, sheet.title), (1, None, "Notes finals"))

    def test_title_split_over_two_cells_is_not_a_group_row(self):
        rows = parse_table(
            "Curs 2025-26\t\tGrup A\t\n"
            "Nom\tCorreu\tExamen\tTreball\n"
            "Vidal Roca, Anna\tanna@example.com\t8\t9\n"
            "Mir Sala, Berta\tberta@example.com\t6\t7\n"
        )
        sheet = analyse_grades_sheet(rows)
        self.assertEqual((sheet.header_row, sheet.group_row), (1, None))
        self.assertEqual(sheet.title, "Curs 2025-26 · Grup A")
        self.assertEqual(sheet.columns, ["Nom", "Correu", "Examen", "Treball"])

    def test_names_split_over_two_rows_still_make_a_group_row(self):
        rows = parse_table(
            "Nom\tProjecte\tExamen\n"
            "\tfinal\tparcial\n"
            "Vidal Roca, Anna\t8\t9\n"
            "Mir Sala, Berta\t6\t7\n"
        )
        sheet = analyse_grades_sheet(rows)
        self.assertEqual(sheet.group_row, 0)
        self.assertEqual(sheet.columns, ["Nom", "Projecte final", "Examen parcial"])

    def test_group_row_can_be_forced_off(self):
        sheet = analyse_grades_sheet(parse_table(TWO_ROW_TEXT), header_row=1, group_row=False)
        self.assertIsNone(sheet.group_row)
        self.assertFalse(sheet.grouped)

    def test_identifier_columns_are_left_out_by_default(self):
        sheet = analyse_grades_sheet(parse_table(TWO_ROW_TEXT))
        self.assertEqual(sheet.identifier_columns, [1, 2, 3])
        self.assertEqual(sheet.feedback_columns, [4, 5, 6, 7, 8, 9, 10])
        chosen = analyse_grades_sheet(parse_table(TWO_ROW_TEXT), feedback_columns=[2, 10])
        self.assertEqual(chosen.feedback_columns, [2, 10])

    def test_identifier_columns_are_left_out_of_flat_sheets_too(self):
        rows = parse_table(
            "Nom\tCorreu\tExamen\tPunts\n"
            "Vidal Roca, Anna\tanna@example.com\t8\t80\n"
            "Mir Sala, Berta\tberta@example.com\t6\t60\n"
            "Costa Pons, Oriol\toriol@example.com\t7\t70\n"
        )
        sheet = analyse_grades_sheet(rows)
        self.assertEqual(sheet.identifier_columns, [1])
        self.assertEqual(sheet.feedback_columns, [2, 3])

    def test_list_without_header_still_starts_at_the_first_student(self):
        rows = parse_table("Vidal Roca, Anna\t8\t9\nMir Sala, Berta\t6\t7\n")
        self.assertEqual(detect_header_row(rows), 0)


class GroupedFeedbackTests(unittest.TestCase):
    GROUPS = [
        FeedbackGroup(
            "Conceptes 01 (20%)",
            [
                FeedbackEntry("intent 1", "6,00", ["10"], False),
                FeedbackEntry("intent 2", "7,00", ["10"], False),
                FeedbackEntry("total", "6,80", ["10"], True),
            ],
        ),
        FeedbackGroup(
            "Pràctica 02",
            [
                FeedbackEntry("intent 1", "4,00", [""], False),
                FeedbackEntry("intent 3", "8,00", [""], False),
                FeedbackEntry("total", "8,00", [""], True),
            ],
        ),
        FeedbackGroup("Examen", [FeedbackEntry("", "6,25", [""], True)]),
    ]

    def test_horizontal_table_spans_activity_labels_over_their_columns(self):
        html = render_grouped_table(self.GROUPS, title="A1")
        plain = unstyled(html)
        self.assertIn('<th colspan="3">Conceptes 01 (20%)</th>', plain)
        self.assertIn('<th rowspan="2">Examen</th>', plain)
        self.assertIn("<th>Intent 1</th><th>Intent 2</th><th>Total</th>", plain)
        self.assertIn('<th colspan="7">A1</th>', plain)
        self.assertRegex(html, rf'<td style="[^"]*{RESULT_STYLE}">6,80</td>')
        self.assertNotRegex(html, rf'<td style="[^"]*{RESULT_STYLE}">6,25</td>')
        self.assertIn("<tfoot><tr><td><small>10</small></td>", plain)
        self.assertNotIn("\n", html)

    def test_vertical_grid_lines_attempts_up_by_label(self):
        html = render_grouped_table(self.GROUPS, layout=LAYOUT_VERTICAL)
        plain = unstyled(html)
        self.assertIn("<th></th><th>Intent 1</th><th>Intent 2</th><th>Intent 3</th><th>Total</th>", plain)
        self.assertIn("<tr><th>Pràctica 02</th><td>4,00</td><td></td><td>8,00</td><td>8,00</td></tr>", plain)
        # A single-column activity: one empty cell across the attempts, the
        # value under the result label.
        self.assertIn('<tr><th>Examen</th><td colspan="3"></td><td>6,25</td></tr>', plain)
        self.assertIn("<td>6,80<br><small>10</small></td>", plain)
        self.assertRegex(html, rf'<td style="[^"]*{RESULT_STYLE}">6,80')

    def test_grid_matches_attempts_without_case_accents_or_spaces(self):
        groups = [
            FeedbackGroup("A", [FeedbackEntry("Intent 1", "6", [], False), FeedbackEntry("total", "6", [], True)]),
            FeedbackGroup("B", [FeedbackEntry("intent1", "7", [], False), FeedbackEntry("total", "7", [], True)]),
        ]
        plain = unstyled(render_grouped_table(groups, layout=LAYOUT_VERTICAL))
        self.assertIn("<th></th><th>Intent 1</th><th>Total</th>", plain)
        self.assertIn("<tr><th>B</th><td>7</td><td>7</td></tr>", plain)

    def test_final_grade_is_bold_in_both_layouts(self):
        groups = [
            FeedbackGroup("A", [FeedbackEntry("intent 1", "6", [], False), FeedbackEntry("total", "6,80", [], True)]),
            FeedbackGroup("Examen", [FeedbackEntry("", "6,25", [], True)]),
            FeedbackGroup("TOTAL", [FeedbackEntry("", "8,05", [], True, final=True)]),
        ]
        for layout in (LAYOUT_HORIZONTAL, LAYOUT_VERTICAL):
            html = render_grouped_table(groups, layout=layout)
            self.assertRegex(html, rf'<td style="[^"]*{RESULT_STYLE}">8,05</td>')
            self.assertNotRegex(html, rf'<td style="[^"]*{RESULT_STYLE}">6,25</td>')

    def test_grid_names_every_result_label(self):
        groups = [
            FeedbackGroup("A", [FeedbackEntry("intent 1", "6", [], False), FeedbackEntry("total", "6", [], True)]),
            FeedbackGroup("B", [FeedbackEntry("intent 1", "7", [], False), FeedbackEntry("nota", "7", [], True)]),
            FeedbackGroup("C", [FeedbackEntry("intent 1", "8", [], False), FeedbackEntry("Total", "8", [], True)]),
        ]
        plain = unstyled(render_grouped_table(groups, layout=LAYOUT_VERTICAL))
        self.assertIn("<th>Intent 1</th><th>Total / Nota</th>", plain)

    def test_unused_attempts_can_show_a_dash(self):
        rows = parse_table(
            "Nom\tConceptes 01\t\t\tConceptes 02\t\t\tConceptes 03\t\t\n"
            "\tintent 1\tintent 2\ttotal\tintent 1\tintent 2\ttotal\tintent 1\tintent 2\ttotal\n"
            "Vidal Roca, Anna\t10,00\t0,00\t10,00\t6,00\t0,00\t1,20\t0,00\t0,00\t0,00\n"
        )
        sheet = analyse_grades_sheet(rows)
        row = sheet.student_rows[0]
        kept = unstyled(student_feedback(sheet, row, FillOptions(layout=LAYOUT_VERTICAL)))
        self.assertNotIn("—", kept)
        html = student_feedback(sheet, row, FillOptions(layout=LAYOUT_VERTICAL, hide_unused_attempts=True))
        plain = unstyled(html)
        # No second try: the total is the first attempt's grade.
        self.assertIn("<tr><th>Conceptes 01</th><td>10,00</td><td>—</td><td>10,00</td></tr>", plain)
        # A 0 that counts in the total, and an activity not done, keep their zeros.
        self.assertIn("<td>6,00</td><td>0,00</td><td>1,20</td>", plain)
        self.assertIn("<td>0,00</td><td>0,00</td><td>0,00</td>", plain)
        self.assertNotRegex(html, f'style="[^"]*{FAIL_STYLE}[^"]*">—')
        self.assertTrue(FillOptions.from_json('{"hide_unused_attempts": true}').hide_unused_attempts)

    def test_filled_feedback_uses_the_grouped_table(self):
        worksheet = read_worksheet(WORKSHEET_BYTES, "worksheet.csv")
        result = preview(worksheet, parse_table(TWO_ROW_TEXT), FillOptions(layout=LAYOUT_VERTICAL))
        plain = unstyled(result["feedback_sample"])
        self.assertIn("<th>Conceptes 01 (50%)</th>", plain)
        self.assertNotIn("12345678Z", plain)
        self.assertNotIn("5987", plain)
        # TOTAL, the grade column, is the final grade.
        self.assertRegex(result["feedback_sample"], rf'<td style="[^"]*{RESULT_STYLE}">[\d,]+</td></tr></tbody>')


if __name__ == "__main__":
    unittest.main()
