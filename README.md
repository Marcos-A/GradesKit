# GradesKit

GradesKit is a small set of grade tools for the Moodle™ software, available at
<https://gradeskit.marcos-a.com/>. The interface is in Catalan.

Each tool has its own tab and address (`#combina`, `#omple`, `#afegeix`).
Without one in the address, the page opens on the tool last used in that
browser.

It was previously called MoodleGradesMerger. It was renamed because the Moodle
trademark policy does not allow "Moodle" in software or domain names. The
repository moved from `Marcos-A/MoodleGradesMerger` to
[`Marcos-A/GradesKit`](https://github.com/Marcos-A/GradesKit); GitHub
redirects the old URL.

## Merge quizzes

This tool combines several Moodle quiz CSV exports into a single result file.
It is available as:

- a web app for uploading CSV files and downloading the merged result as `CSV` or `XLSX`
- a CLI that keeps the original script workflow for local folders of CSV files

### What the tool accepts

The web app accepts:

- one or more Moodle CSV export files
- one ZIP file that contains Moodle CSV export files

Files can be dragged onto the upload box or chosen with a click; either way
they replace the previous selection. Dropped files with another extension are
rejected.

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
   UTF-8 or Windows-1252). The last choice is remembered in the browser
   (`localStorage`).

Files can be dragged onto either upload box or chosen with a click. A dropped
file with another extension is rejected before it is sent.

### How the grades sheet is read

- The header row is the first row that is (almost) as full as the widest
  rows, so title rows such as `TOTAL A1 (1a convocatòria)` are skipped and
  used as the feedback table title.
- The name column is the one whose values look most like names
  (`Cognoms, Nom` or `Nom Cognoms`).
- The **grade is the last column** by default; any other column can be
  chosen.
- Percent cells (`50%`) in the rows after the last student, or in a row of
  percents above the header, are read as the **weight** of each column and
  shown in its feedback header: `Examen (50%)`. Columns whose header already
  includes a percent are left as they are.
- Weights can be typed, changed or cleared next to each feedback column, which
  helps when the pasted grades have no percents. `50`, `50%`, `12,5%` and
  `0,5` are accepted.
- Other values in those rows (maximum grades such as `10,00`) are left out
  unless *Inclou la fila al peu* is checked; they are then shown as a footer
  row, without the percents already shown as weights.
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
  It has the sheet title, the chosen columns with their weights in the
  headers, and the footer row only when *Inclou la fila al peu* is checked.
- The file is UTF-8 and comma-separated, the defaults of Moodle's upload form.

### Uploading to Moodle

*Submissions* → *Upload grading worksheet*. If students already had a grade,
tick *Allow updating records that have been modified more recently in Moodle
than in the spreadsheet*. Moodle cannot parse localised dates such as
`dimecres, 7 d’octubre 2026` in the worksheet, so without that option it
treats every existing grade as newer and skips it.

## Add grades

This tool finds each student's grade for the teacher's own student list, for
example the grades of a new exam, and copies them to the clipboard with one
click, ready to paste into a spreadsheet beside that list.

### The two lists

Both lists are pasted from a spreadsheet or uploaded as a CSV, like the final
grades of the fill tool. Each list remembers the last choice in the browser
(`localStorage`); if storage is blocked, it starts on pasting.

Each step says in one line what it expects, with the details below the box.

1. **Main list**: the teacher's students, one per row, with the names
   (`Nom Cognoms` or `Cognoms, Nom`) in any column, usually the first or
   second, and any other columns (IDs, exercise grades…). Title rows above
   the header are allowed.
2. **Grades to add**: usually the assignment grading worksheet downloaded
   from Moodle (*Full de qualificacions*), or any list with at least a column
   of names and one or more grade columns. `Qualificació` or `Qualificacions`
   is selected by default (ignoring accents and case), falling back to the
   last column with values. Use **Columnes de notes** in the review step to
   select one or more columns. Moodle's `-` counts as a missing grade.

Problems are reported as soon as a list is in, without waiting for the
other one:

- an error, above the boxes, when no column of names is found or when the
  grades list has a single column;
- a warning, below the boxes, when most "names" in the main list are a
  single word (IDs, groups, first names only), or when a selected grade column
  has text values but no numbers.

A row with a number in it is never taken as a header, and neither is a
guessed header that matches a student of the other list, so lists that start
directly with a student work too. Pasted text is split on tabs only, so a
one-column paste of `Cognoms, Nom` stays whole. The preview names the header
row left out of the result, in case a student was taken for it. The header
rows and the name columns can also be changed in the review step.

### How names are matched

It uses the same matching as the fill tool: `Nom Cognoms` and
`Cognoms, Nom` are the same person, accents and punctuation are ignored, and
a missing middle name or second surname is accepted. A missing word combined
with a small spelling difference (`Garsia, Maria` / `María García Puig`) is
also accepted when every word of the shorter name is close to a word of the
longer one.

Unlike the fill tool, close matches (*Semblant*) are used straight away;
they are highlighted, like ambiguous students (*Dubtós*), so they can be
checked and changed. The matching table is sorted alphabetically.

- Each selected column gets a `0` for a student missing from the grades list.
  For matched students, an empty cell or `-` becomes `0` in that column.
- Students who only appear in the grades list are shown in a warning with
  their selected grades and are left out of the result.

### What is copied

No header: one row per row of the main list after its header, in the same
order and blank rows included, so the result lines up when pasted beside the
first student. Empty rows at the end, such as footers, are left out. The
selected columns keep their order in the grades list. Choose one of these formats.

- **Nom i notes** copies the student's name as written in the main list,
  followed by the selected grades.
- **Només les notes** copies just the selected grades.

The choice is remembered in the browser. Grades are copied with a
decimal comma (`7.25` becomes `7,25`); text such as `NP` stays as written. The text is tab-separated, which is what
spreadsheets expect on the clipboard; only cells with a tab or a line break
are quoted.

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
- [`gradeskit/add_grades.py`](gradeskit/add_grades.py): add-grades tool (list detection, matching and copied text)
- [`gradeskit/moodle_worksheet.py`](gradeskit/moodle_worksheet.py): grading worksheet headers per language, reading and writing
- [`gradeskit/grades_sheet.py`](gradeskit/grades_sheet.py): detection of header, name, grade, weights and footer rows in the teacher's sheet
- [`gradeskit/matching.py`](gradeskit/matching.py): student name matching
- [`gradeskit/feedback_html.py`](gradeskit/feedback_html.py): feedback table HTML
- [`gradeskit/tabular.py`](gradeskit/tabular.py): CSV and clipboard parsing helpers
- [`gradeskit/xlsx.py`](gradeskit/xlsx.py): minimal XLSX writer
- [`gradeskit/build_info.py`](gradeskit/build_info.py): build and release identification
- [`gradeskit/__main__.py`](gradeskit/__main__.py): CLI entrypoint
- [`scripts/`](scripts/): deployment and build-identification scripts
- [`tests/`](tests/): regression tests
- [`Dockerfile`](Dockerfile): container image used for local runs and deployment

## Tests

```bash
python -m unittest discover -s tests
```

## Docker deployment

The container starts the built-in Python web server on port `8000`. The application is intentionally standard-library-only so the image can be built and deployed without installing third-party Python packages.

The production container is defined in `/srv/compose/gradeskit/compose.yml`.
Deploy from a clean checkout with:

```bash
scripts/deploy.sh
```

### Build identification

Every deployment shows which commit it runs, without needing a release:

- [`scripts/build-env.sh`](scripts/build-env.sh) bakes the commit SHA and
  build time into the image (also its `org.opencontainers.image.revision`
  label). It refuses an invalid SHA or uncommitted changes (`ALLOW_DIRTY=1`
  overrides).
- [`scripts/update-release-info.sh`](scripts/update-release-info.sh) writes the
  latest published GitHub release (via `gh` on the host) to
  `build-meta/release-info.json`, mounted read-only into the container.
  Deploying never creates or bumps a release. After publishing one
  (`gh release create v2.1.0 --generate-notes`), run
  `scripts/update-release-info.sh build-meta/release-info.json "$(docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' gradeskit-web:local)"`;
  the app picks it up without a rebuild. If no release can be verified, none
  is shown.
- `APP_ENV` (`production` or `preview`), `REPO_URL` and `REPO_VISIBILITY` are
  runtime settings in the compose file.
- Both scripts are unchanged copies of the canonical `app-build-info` v1
  scripts (see their header); update them by re-copying, not by editing here.

`GET /build-info.json` returns the environment, `build.sha`/`shortSha`/`builtAt`
and the `release` (or `null`). The page footer shows `v2.0.0 · 3507843`, or
`Build 3507843` with no release, `Preview · 3507843` outside production, and
`Build unknown` when the image was built without `scripts/deploy.sh` (for
example a plain `docker build`). With `REPO_VISIBILITY=private` it shows only
the release.

## License

This project is licensed under `AGPL-3.0-only`. See [LICENSE](LICENSE).
