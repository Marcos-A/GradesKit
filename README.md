# GradesKit

GradesKit is a small set of grade tools for the Moodle™ software, available at
<https://gradeskit.marcos-a.com/>. The interface is in Catalan.

It was previously called MoodleGradesMerger. It was renamed because the Moodle
trademark policy does not allow "Moodle" in software or domain names.

## Merge quizzes

This tool combines several Moodle quiz CSV exports into a single result file.
It is available as:

- a web app for uploading CSV files and downloading the merged result as `CSV` or `XLSX`
- a CLI that keeps the original script workflow for local folders of CSV files

### What the tool accepts

The web app accepts:

- one or more Moodle CSV export files
- one ZIP file that contains Moodle CSV export files

Folder uploads and TAR/TGZ archives are no longer part of the web workflow. This keeps the interface simpler and avoids browser-specific behavior.

### What the generated file contains

The merged file is grouped by student and exercise.

- The output keeps the student name as `Cognoms, Nom`.
- The email column is used internally to match the same student across files, but it is not included in the final downloadable result.
- Exercises are sorted alphabetically so repeated runs produce a stable column order.

There are two output layouts, depending on the grading strategy:

#### `highest`

This is the original behavior of the repository.

For each exercise, the result contains only one final grade column with the best valid score.

#### `average` and `weighted`

These strategies keep more detail in the downloadable file:

- one column per attempt: `intent 1`, `intent 2`, and so on
- one `total` column with the final grade used for that exercise

Even if an exercise has only one attempt, the result still shows `intent 1` and `total` so the table shape remains consistent.

### Grading strategies

The application offers three strategies:

- `highest`: keep only the highest valid grade
- `average`: average all valid grades
- `weighted`: assign a percentage to the highest valid grade and distribute the remaining percentage equally across the other valid grades

In `average` and `weighted`, attempts with a zero grade or no submission are ignored. This follows the project’s long-standing weighted-grade rule and avoids lowering the result with missing work markers from Moodle.

If an exercise has only one valid grade, that grade is used directly in every strategy.

### Weighted percentage input

In the web app, the weighted field is always interpreted as a percentage.

- If the user omits the `%` sign, the interface adds it automatically.
- Whole numbers and decimal percentages are accepted.
- The allowed range is from `0` to `100`.
- The web interface shows decimals with a comma, for example `12,5%`.

Examples of accepted web inputs:

- `80%`
- `80`
- `12,5%`
- `12,5`

The CLI remains slightly more permissive for backwards compatibility and still accepts ratio-style inputs such as `0.8`.

### Moodle CSV expectations

The parser expects Moodle export headers to contain these Catalan labels:

- `Adreça electrònica` for email
- `Nom` for name
- `Cognoms` for surname
- `Qualificació` for grade

If your Moodle instance exports different column names, update the markers in [`gradeskit/quiz_merge.py`](gradeskit/quiz_merge.py).

## Fill an assignment

This tool fills the **grade** and **feedback comments** columns of an
assignment grading worksheet with the teacher's final grades, ready to upload
back to Moodle.

### Inputs

1. The grading worksheet CSV, unmodified. In the assignment: *Submissions* →
   *Download grading worksheet*. The assignment needs the *Offline grading
   worksheet* and *Feedback comments* feedback types enabled.
2. The final grades, either pasted from a spreadsheet (copying cells puts the
   displayed values on the clipboard as tab-separated text, so formulas and
   formatting are ignored) or uploaded as a CSV (comma or semicolon,
   UTF-8 or Windows-1252).

### How the grades sheet is read

- The header row is the first row that is (almost) as full as the widest
  rows, so title rows such as `TOTAL A1 (1a convocatòria)` are skipped and
  used as the feedback table title.
- The name column is the one whose values look most like names
  (`Cognoms, Nom` or `Nom Cognoms`).
- The **grade is the last column** by default; any other column can be
  chosen.
- Rows after the last student without a name (weights such as `50%`, maximum
  grades) are shown as a footer row in the feedback.
- A row-counter column (`1, 2, 3…`) is left out of the feedback by default.

Every guess can be changed in the review step.

### Matching students

Names are compared as words without accents or punctuation, and
`Cognoms, Nom` is reordered to `Nom Cognoms`, which is how Moodle writes the
full name. If the grades include an email column, emails are compared first.

- Same words → matched.
- Every word of the shorter name appears in the longer one (a missing second
  surname), or a very similar spelling → **probable**: the teacher must
  confirm it before it is used.
- Two equally good candidates → left unmatched, so the teacher chooses.

Participants without a grade are left exactly as they were.

### What the output keeps

Moodle finds the worksheet columns by their exact header text in the user's
language, so the header row is never changed. Worksheets in Catalan, Spanish,
English, Galician, Basque, French, Portuguese, Italian and German are
recognised (strings taken from the official language packs).

- Grades use the same decimal separator as the worksheet's maximum grade.
  Moodle reads them with the user's locale, where `.` can be a thousands
  separator.
- Grades outside `0`–maximum are not written; Moodle would silently skip them.
- Feedback is a single-line HTML table with Bootstrap classes
  (`table table-sm table-bordered`); Moodle stores imported comments as HTML.
- The file is UTF-8 and comma-separated, the defaults of Moodle's upload form.

### Uploading to Moodle

*Submissions* → *Upload grading worksheet*. If students already had a grade,
tick *Allow updating records that have been modified more recently in Moodle
than in the spreadsheet*. Moodle cannot parse localised dates such as
`dimecres, 7 d’octubre 2026` in the worksheet, so without that option it
treats every existing grade as newer and skips it.

## Local run with Docker

Build and run locally:

```bash
docker build -t gradeskit .
docker run --rm -p 8000:8000 gradeskit
```

The app runs on `http://127.0.0.1:8000`.

## CLI usage

The quiz merge tool can also run from the command line:

```bash
python3 -m gradeskit merge /path/to/CSVFilesFolder
python3 -m gradeskit merge /path/to/CSVFilesFolder 0.8
```

Passing a percentage switches to weighted mode. The CLI uses the same logic as the web app, so both give the same results. It replaces the old `MoodleGradesMerger.py` script.

## Project structure

- [`app.py`](app.py): dependency-free WSGI web app (routes only)
- [`templates/index.html`](templates/index.html): page markup, rendered with `string.Template`
- [`static/`](static/): stylesheet and the browser scripts for each tool
- [`gradeskit/quiz_merge.py`](gradeskit/quiz_merge.py): quiz parsing, grade calculation, and CSV generation
- [`gradeskit/fill.py`](gradeskit/fill.py): fill tool flow (preview and filled worksheet)
- [`gradeskit/moodle_worksheet.py`](gradeskit/moodle_worksheet.py): grading worksheet headers per language, reading and writing
- [`gradeskit/grades_sheet.py`](gradeskit/grades_sheet.py): detection of header, name, grade and footer rows in the teacher's sheet
- [`gradeskit/matching.py`](gradeskit/matching.py): student name matching
- [`gradeskit/feedback_html.py`](gradeskit/feedback_html.py): feedback table HTML
- [`gradeskit/tabular.py`](gradeskit/tabular.py): CSV and clipboard parsing helpers
- [`gradeskit/xlsx.py`](gradeskit/xlsx.py): minimal XLSX writer
- [`gradeskit/__main__.py`](gradeskit/__main__.py): CLI entrypoint
- [`tests/`](tests/): regression tests
- [`Dockerfile`](Dockerfile): container image used for local runs and deployment

## Tests

```bash
python -m unittest discover -s tests
```

## Docker deployment

The container starts the built-in Python web server on port `8000`. The application is intentionally standard-library-only so the image can be built and deployed without installing third-party Python packages.
