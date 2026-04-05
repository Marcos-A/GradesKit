# MoodleGradesMerger

Web app and CLI utility for merging Moodle grade CSV files into a single downloadable result file.

The original project kept the highest grade for each exercise. This version keeps that behavior and adds:

- Upload for one or more CSV files
- ZIP archive support for CSV bundles
- CSV or XLSX download for the generated result
- Three grading strategies:
  - `highest`: keep only the highest valid grade
  - `average`: average all valid grades
  - `weighted`: assign a weight to the highest grade and distribute the remaining percentage equally across the other valid grades

Zero grades and non-submissions are ignored for `average` and `weighted`, following the original README behavior for weighted calculations.

## Moodle CSV expectations

The parser still expects the Moodle export headers to contain these Catalan labels:

- `Adreça electrònica` for email
- `Nom` for name
- `Cognoms` for surname
- `Qualificació` for grade

If your Moodle instance exports different column names, update the markers in [merger.py](/Users/marcosalcocergil/Documents/Dropbox/GitHub/MoodleGradesMerger/merger.py).

## Grading rules

### Highest grade

For each exercise, only the best valid grade is kept.

### Average of all grades

For each exercise, all valid grades above zero are averaged equally.

### Weighted highest grade

The highest valid grade receives a chosen percentage, and the remaining percentage is split equally between the other valid grades.

Examples of accepted percent inputs:

- `80%`
- `80`
- `0.8`
- `0,8`

If there is only one valid grade, that grade is used directly.

## Local run with Docker

Build and run locally:

```bash
docker build -t moodle-grades-merger .
docker run --rm -p 8000:8000 moodle-grades-merger
```

The app runs on `http://127.0.0.1:8000`.

## CLI usage

To preserve the original command-line workflow:

```bash
python3 MoodleGradesMerger.py /path/to/CSVFilesFolder
python3 MoodleGradesMerger.py /path/to/CSVFilesFolder 0.8
```

Passing a second argument switches to the weighted mode.

## Tests

```bash
python -m unittest discover -s tests
```

## Docker deployment

The container starts the built-in Python web server on port `8000`, which is suitable for deployment on the containers server.
