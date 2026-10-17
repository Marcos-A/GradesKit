"""Command-line entrypoint: `python -m gradeskit merge FOLDER [percent]`.

The original repository was a script-only tool. The CLI keeps that workflow
for local folders of quiz CSV files and uses the same rules as the web app.
"""

from sys import argv

from gradeskit.quiz_merge import STRATEGY_HIGHEST, STRATEGY_WEIGHTED, merge_path_to_csv, normalize_percent

USAGE = "Usage: python -m gradeskit merge /path/to/CSVFilesFolder [percent]"


def main(args: list[str]) -> None:
    if len(args) < 2 or args[0] != "merge":
        raise SystemExit(USAGE)

    # Preserve the old behavior: without a percentage we keep only the highest
    # grade; passing one switches to weighted mode.
    strategy = STRATEGY_HIGHEST
    weighted_percent = 0.8
    if len(args) > 2:
        strategy = STRATEGY_WEIGHTED
        weighted_percent = normalize_percent(args[2])

    output_path = merge_path_to_csv(
        input_path=args[1],
        strategy=strategy,
        weighted_percent=weighted_percent,
    )
    print(output_path)


if __name__ == "__main__":
    main(argv[1:])
