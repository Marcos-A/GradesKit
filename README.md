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
