#!/usr/bin/env python3
"""Command-line entrypoint kept for backwards compatibility.

The original repository was a script-only tool. The main logic now lives in
`merger.py`, and this file simply translates command-line arguments into that
shared API.
"""

from sys import argv

from merger import STRATEGY_HIGHEST, STRATEGY_WEIGHTED, merge_path_to_csv, normalize_percent


if __name__ == "__main__":
    if len(argv) < 2:
        raise SystemExit("Usage: python MoodleGradesMerger.py /path/to/CSVFilesFolder [percent]")

    # Preserve the old behavior: without a second argument we keep only the
    # highest grade; passing a percentage switches to weighted mode.
    strategy = STRATEGY_HIGHEST
    weighted_percent = 0.8
    if len(argv) > 2:
        strategy = STRATEGY_WEIGHTED
        weighted_percent = normalize_percent(argv[2])

    output_path = merge_path_to_csv(
        input_path=argv[1],
        strategy=strategy,
        weighted_percent=weighted_percent,
    )
    print(output_path)
