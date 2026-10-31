"""Tests for the add-grades tool: list detection, fuzzy matching and the copied text."""

import json
import unittest

from gradeskit.add_grades import (
    NO_HEADER,
    NO_STUDENT,
    OUTPUT_GRADE,
    AddGradesOptions,
    detect_list_header,
    preview,
    rows_to_tsv,
    with_decimal_comma,
)
from gradeskit.matching import STATUS_PROBABLE, Person, match_people
from gradeskit.tabular import parse_table

MASTER_TEXT = (
    "Grup 1A\t\t\t\n"
    "ID\tESTUDIANT\t\tExercici 1\n"
    "101\tCosta Pons, Oriol\t\t8\n"
    "102\tMir Sala, Berta Aina\t\t4,5\n"
    "103\tGarcía Puig, María\t\t7\n"
    "104\tRomero, Hugo\t\t9\n"
)
GRADES_TEXT = (
    "Nom\tExamen\n"
    "Oriol Costa Pons\t7,25\n"
    "Berta Mir\t6\n"
    "Maria Garsia\t5\n"
    "Laia Ferrer Soler\t8\n"
)


def run(master: str = MASTER_TEXT, grades: str = GRADES_TEXT, options: AddGradesOptions | None = None) -> dict:
    # Both lists as pasted from a spreadsheet, split on tabs like the app does.
    master_rows = parse_table(master, keep_blank=True, delimiter="\t")
    return preview(master_rows, parse_table(grades, delimiter="\t"), options or AddGradesOptions())


def by_name(result: dict) -> dict[str, dict]:
    return {student["name"]: student for student in result["students"]}


class ListDetectionTests(unittest.TestCase):
    def test_keep_blank_keeps_spacer_columns_but_not_trailing_ones(self):
        self.assertEqual(parse_table("a\t\tb\t\n\n1\t\t2\t\n\n", keep_blank=True), [["a", "", "b"], ["", "", ""], ["1", "", "2"]])

    def test_header_after_a_title_row(self):
        result = run()
        self.assertEqual(result["master"]["header_row"], 1)
        self.assertEqual(result["master"]["name_column"], 1)
        self.assertEqual(result["master"]["student_rows"], [2, 3, 4, 5])

    def test_list_without_header(self):
        rows = parse_table("Costa Pons, Oriol\t7\nRomero, Hugo\t9\n")
        self.assertEqual(detect_list_header(rows), NO_HEADER)

    def test_grade_comes_from_the_qualificacions_column(self):
        grades = "Nom\tQualificacions\tComentari\nOriol Costa Pons\t7\tBé\n"
        self.assertEqual(by_name(run(grades=grades))["Costa Pons, Oriol"]["grade"], "7")
        grades = "Nom\tQUALIFICACIÓ\tComentari\nOriol Costa Pons\t6\tBé\n"
        self.assertEqual(by_name(run(grades=grades))["Costa Pons, Oriol"]["grade"], "6")


class MatchingTests(unittest.TestCase):
    def test_missing_words_and_typos_are_matched(self):
        students = by_name(run())
        self.assertEqual(students["Costa Pons, Oriol"]["grade"], "7,25")
        self.assertEqual(students["Mir Sala, Berta Aina"]["grade"], "6")
        self.assertEqual(students["García Puig, María"]["grade"], "5")
        self.assertEqual(students["García Puig, María"]["status"], STATUS_PROBABLE)

    def test_different_first_names_do_not_match(self):
        matches = match_people([Person(1, "Vidal Roca, Pau")], [Person(2, "Pol Vidal")])
        self.assertIsNone(matches[1].candidate)

    def test_missing_student_gets_zero(self):
        student = by_name(run())["Romero, Hugo"]
        self.assertIsNone(student["grades_row"])
        self.assertEqual(student["grade"], "0")

    def test_empty_grade_gets_zero(self):
        grades = "Nom\tQualificacions\nOriol Costa Pons\t\nHugo Romero\t9\n"
        result = run(grades=grades)
        self.assertEqual(by_name(result)["Costa Pons, Oriol"]["grade"], "0")
        self.assertIn("Costa Pons, Oriol\t0", result["text"].splitlines())

    def test_students_only_in_grades_are_reported(self):
        result = run()
        self.assertEqual([student["name"] for student in result["unused"]], ["Laia Ferrer Soler"])

    def test_manual_choices_win(self):
        result = run(options=AddGradesOptions(matches={2: NO_STUDENT, 5: 4}))
        students = by_name(result)
        self.assertEqual(students["Costa Pons, Oriol"]["grade"], "0")
        self.assertEqual(students["Romero, Hugo"]["grade"], "8")
        self.assertEqual([student["name"] for student in result["unused"]], ["Oriol Costa Pons"])

    def test_options_round_trip_from_json(self):
        options = AddGradesOptions.from_json(json.dumps({"master_header_row": -1, "grades_grade_column": "1", "matches": {"3": -1}}))
        self.assertEqual(options.master_header_row, NO_HEADER)
        self.assertEqual(options.grades_grade_column, 1)
        self.assertEqual(options.matches, {3: NO_STUDENT})
        self.assertEqual(options.output, "name_grade")
        self.assertEqual(AddGradesOptions.from_json('{"output": "grade"}').output, OUTPUT_GRADE)


class OutputTests(unittest.TestCase):
    def test_text_has_name_and_grade_without_header(self):
        lines = run()["text"].splitlines()
        self.assertEqual(lines[0], "Costa Pons, Oriol\t7,25")
        self.assertEqual(lines[3], "Romero, Hugo\t0")
        self.assertEqual(len(lines), 4)

    def test_text_can_have_only_the_grade(self):
        text = run(options=AddGradesOptions(output=OUTPUT_GRADE))["text"]
        self.assertEqual(text, "7,25\n6\n5\n0\n")

    def test_blank_rows_between_students_are_kept_and_footer_dropped(self):
        master = "Nom\tNota\nCosta Pons, Oriol\t8\n\t\nRomero, Hugo\t9\n\t10\n"
        text = run(master=master, options=AddGradesOptions(output=OUTPUT_GRADE))["text"]
        self.assertEqual(text, "7,25\n\n0\n")

    def test_grades_use_a_decimal_comma(self):
        grades = "Nom\tQualificacions\nOriol Costa Pons\t7.25\nHugo Romero\tNP\n"
        text = run(grades=grades, options=AddGradesOptions(output=OUTPUT_GRADE))["text"]
        self.assertEqual(text, "7,25\n0\n0\nNP\n")
        self.assertEqual(with_decimal_comma("8"), "8")
        self.assertEqual(with_decimal_comma("6,5"), "6,5")
        self.assertEqual(with_decimal_comma("1.234,5"), "1.234,5")
        self.assertEqual(with_decimal_comma("1,234.5"), "1234,5")
        self.assertEqual(with_decimal_comma("Dr. Who"), "Dr. Who")

    def test_cells_with_tabs_or_line_breaks_are_quoted(self):
        self.assertEqual(rows_to_tsv([["a\tb", 'c "d"'], ["", "e\nf"]]), '"a\tb"\tc "d"\n\t"e\nf"\n')

    def test_grade_column_can_be_chosen(self):
        grades = "Nom\tNota\tComentari\nOriol Costa Pons\t7\tBé\n"
        self.assertEqual(by_name(run(grades=grades))["Costa Pons, Oriol"]["grade"], "Bé")
        options = AddGradesOptions(grades_grade_column=1)
        self.assertEqual(by_name(run(grades=grades, options=options))["Costa Pons, Oriol"]["grade"], "7")

    def test_one_list_alone_is_described(self):
        result = preview(parse_table(MASTER_TEXT, keep_blank=True), None, AddGradesOptions())
        self.assertIsNotNone(result["master"])
        self.assertEqual(result["text"], "")

    def test_list_without_header_keeps_its_first_student(self):
        master = "Costa Pons, Oriol\toriol@example.cat\nRomero, Hugo\thugo@example.cat\n"
        result = run(master=master)
        self.assertEqual(result["master"]["header_row"], NO_HEADER)
        self.assertEqual(result["text"], "Costa Pons, Oriol\t7,25\nRomero, Hugo\t0\n")

    def test_header_chosen_by_the_teacher_is_kept(self):
        master = "Costa Pons, Oriol\nRomero, Hugo\n"
        result = run(master=master, options=AddGradesOptions(master_header_row=0))
        self.assertEqual(result["text"], "Romero, Hugo\t0\n")

    def test_one_word_headers_are_never_students(self):
        master = "Grup 1A\nNom\nCosta Pons, Oriol\n"
        grades = "Nom\tQualificacions\nOriol Costa Pons\t7\n"
        result = run(master=master, grades=grades)
        self.assertEqual(result["grades"]["header_row"], 0)
        self.assertEqual(result["master"]["header_row"], 1)
        self.assertEqual(result["text"], "Costa Pons, Oriol\t7\n")

    def test_one_column_paste_is_not_split_at_commas(self):
        rows = parse_table("Costa Pons, Oriol\nRomero, Hugo\n", keep_blank=True, delimiter="\t")
        self.assertEqual(rows, [["Costa Pons, Oriol"], ["Romero, Hugo"]])

    def test_grades_need_two_columns(self):
        with self.assertRaises(ValueError):
            run(grades="Oriol Costa Pons\nHugo Romero\n")


if __name__ == "__main__":
    unittest.main()
