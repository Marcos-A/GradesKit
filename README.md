# MoodleGradesMerger

MoodleGradesMerger combines several Moodle CSV exports into a single result file.

The project now has two entrypoints:

- a web app for uploading CSV files and downloading the merged result as `CSV` or `XLSX`
- a legacy CLI wrapper that preserves the original script workflow for local folders of CSV files

## What the app accepts

The web app accepts:

- one or more Moodle CSV export files
- one ZIP file that contains Moodle CSV export files

Folder uploads and TAR/TGZ archives are no longer part of the web workflow. This keeps the interface simpler and avoids browser-specific behavior.

## What the generated file contains

The merged file is grouped by student and exercise.

- The output keeps the student name as `Cognoms, Nom`.
- The email column is used internally to match the same student across files, but it is not included in the final downloadable result.
- Exercises are sorted alphabetically so repeated runs produce a stable column order.

There are two output layouts, depending on the grading strategy:

### `highest`

This is the original behavior of the repository.

For each exercise, the result contains only one final grade column with the best valid score.

### `average` and `weighted`

These strategies keep more detail in the downloadable file:

- one column per attempt: `intent 1`, `intent 2`, and so on
- one `total` column with the final grade used for that exercise

Even if an exercise has only one attempt, the result still shows `intent 1` and `total` so the table shape remains consistent.

## Grading strategies

The application offers three strategies:

- `highest`: keep only the highest valid grade
- `average`: average all valid grades
- `weighted`: assign a percentage to the highest valid grade and distribute the remaining percentage equally across the other valid grades

In `average` and `weighted`, attempts with a zero grade or no submission are ignored. This follows the project’s long-standing weighted-grade rule and avoids lowering the result with missing work markers from Moodle.

If an exercise has only one valid grade, that grade is used directly in every strategy.

## Weighted percentage input

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

## Moodle CSV expectations

The parser expects Moodle export headers to contain these Catalan labels:

- `Adreça electrònica` for email
- `Nom` for name
- `Cognoms` for surname
- `Qualificació` for grade

If your Moodle instance exports different column names, update the markers in [`merger.py`](merger.py).

## Local run with Docker

Build and run locally:

```bash
docker build -t moodle-grades-merger .
docker run --rm -p 8000:8000 moodle-grades-merger
```

The app runs on `http://127.0.0.1:8000`.

## CLI usage

The original script interface is still available:

```bash
python3 MoodleGradesMerger.py /path/to/CSVFilesFolder
python3 MoodleGradesMerger.py /path/to/CSVFilesFolder 0.8
```

Passing a second argument switches to weighted mode. The CLI uses the shared logic from [`merger.py`](merger.py), so script and web results follow the same core grading rules.

## Project structure

- [`app.py`](app.py): dependency-free web app and inline HTML/JavaScript UI
- [`merger.py`](merger.py): shared parsing, grade calculation, and CSV/XLSX generation logic
- [`MoodleGradesMerger.py`](MoodleGradesMerger.py): legacy CLI entrypoint
- [`tests/test_merger.py`](tests/test_merger.py): regression tests for the merge logic
- [`Dockerfile`](Dockerfile): container image used for local runs and deployment

## Tests

```bash
python -m unittest discover -s tests
```

## Docker deployment

The container starts the built-in Python web server on port `8000`. The application is intentionally standard-library-only so the image can be built and deployed without installing third-party Python packages.
