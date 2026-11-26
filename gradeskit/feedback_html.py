"""Render the per-student feedback table stored in Moodle's feedback comments.

Moodle saves imported feedback comments as HTML and styles tables with
Bootstrap, so the built-in table classes give the borders and spacing. Colours
and alignment are inline styles on each cell: Moodle keeps them, and they do
not depend on the theme. The look follows the teachers' grades sheets: green
header cells with white text, light green stripes, and failing grades and
"NP" (no presentat) in red.
The HTML is kept on a single line so the CSV cell stays simple.
"""

from dataclasses import dataclass
from html import escape

from gradeskit.tabular import parse_number, strip_accents

LAYOUT_HORIZONTAL = "horizontal"
LAYOUT_VERTICAL = "vertical"
TABLE_OPEN = '<table class="table table-sm table-bordered">'
PASS_GRADE = 5
# Marks shown in red like a failing grade, compared without case.
FAIL_MARKS = {"NP"}

CENTER = "text-align:center;vertical-align:middle"
TITLE_STYLE = f"{CENTER};background-color:#38761d;color:#ffffff;font-weight:bold"
HEADER_STYLE = f"{CENTER};background-color:#6aa84f;color:#ffffff;font-weight:bold"
# Row headers in the vertical table are text read down a column, so they are
# left-aligned like text in a spreadsheet.
ROW_HEADER_STYLE = HEADER_STYLE.replace("text-align:center", "text-align:left")
STRIPE_BACKGROUND = "background-color:#d9ead3"
FAIL_STYLE = "color:#e00000"
# Column labels under an activity ("intent 1", "total") in two-row headers.
SUBHEADER_STYLE = f"{CENTER};background-color:#b6d7a8;color:#274e13;font-weight:bold;white-space:nowrap"
RESULT_STYLE = "font-weight:bold"


@dataclass
class FeedbackEntry:
    """One column of an activity: its own label, the value and footer values."""

    sub: str
    value: str
    footers: list[str]
    # The activity's result column ("total"), the last one in the sheet.
    result: bool


@dataclass
class FeedbackGroup:
    label: str
    entries: list[FeedbackEntry]

    @property
    def spans(self) -> bool:
        """Shown with its own column labels under the activity label."""

        return len(self.entries) > 1 or bool(self.entries[0].sub)


def _value_style(value: str, striped: bool) -> str:
    """Centre a value, shade striped rows and show numbers under 5 and NP in red."""

    parts = [CENTER]
    if striped:
        parts.append(STRIPE_BACKGROUND)
    number = parse_number(value)
    if (number is not None and number < PASS_GRADE) or value.strip().upper() in FAIL_MARKS:
        parts.append(FAIL_STYLE)
    return ";".join(parts)


def _cell(
    tag: str, value: str, style: str, small: bool = False, colspan: int | None = None, rowspan: int | None = None
) -> str:
    text = f"<small>{escape(value)}</small>" if small else escape(value)
    span = (f' colspan="{colspan}"' if colspan else "") + (f' rowspan="{rowspan}"' if rowspan else "")
    return f'<{tag}{span} style="{style}">{text}</{tag}>'


def _value_cells(values: list[str], striped: bool, small: bool = False) -> str:
    return "".join(_cell("td", value, _value_style(value, striped), small) for value in values)


def render_feedback_table(
    headers: list[str],
    values: list[str],
    footer_rows: list[list[str]],
    title: str = "",
    layout: str = LAYOUT_HORIZONTAL,
) -> str:
    """Build the feedback table for one student.

    `footer_rows` hold extra rows from the sheet such as maximum grades; rows
    that are empty for the chosen columns are left out.
    """

    if not headers:
        return ""
    footer_rows = [row for row in footer_rows if any(row)]

    if layout == LAYOUT_VERTICAL:
        width = 2 + len(footer_rows)
        title_html = f"<thead><tr>{_cell('th', title, TITLE_STYLE, colspan=width)}</tr></thead>" if title else ""
        body = "".join(
            f"<tr>{_cell('th', header, ROW_HEADER_STYLE)}"
            + _value_cells([value], striped=index % 2 == 1)
            + _value_cells([row[index] for row in footer_rows], striped=index % 2 == 1, small=True)
            + "</tr>"
            for index, (header, value) in enumerate(zip(headers, values))
        )
        return f"{TABLE_OPEN}{title_html}<tbody>{body}</tbody></table>"

    title_html = f"<tr>{_cell('th', title, TITLE_STYLE, colspan=len(headers))}</tr>" if title else ""
    header_html = "".join(_cell("th", header, HEADER_STYLE) for header in headers)
    # The student's row is white and the footer rows continue the stripes.
    footer_html = (
        "<tfoot>"
        + "".join(
            f"<tr>{_value_cells(row, striped=index % 2 == 0, small=True)}</tr>"
            for index, row in enumerate(footer_rows)
        )
        + "</tfoot>"
        if footer_rows
        else ""
    )
    return (
        f"{TABLE_OPEN}<thead>{title_html}<tr>{header_html}</tr></thead>"
        f"<tbody><tr>{_value_cells(values, striped=False)}</tr></tbody>{footer_html}</table>"
    )


def _label_key(label: str) -> str:
    """Compare column labels without case, accents or spacing ("Intent 1" = "intent1")."""

    return "".join(strip_accents(label).casefold().split())


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _grid_cell(entry: FeedbackEntry | None, striped: bool, bold: bool) -> str:
    """A grid cell with the value and, in small type below it, its footer values."""

    if entry is None:
        return f'<td style="{_value_style("", striped)}"></td>'
    style = _value_style(entry.value, striped) + (f";{RESULT_STYLE}" if bold else "")
    footers = "".join(f"<br><small>{escape(value)}</small>" for value in entry.footers if value)
    return f'<td style="{style}">{escape(entry.value)}{footers}</td>'


def _render_grid(groups: list[FeedbackGroup], title: str) -> str:
    """One row per activity and one column per attempt label, with the result last.

    Attempts are lined up by label, so activities with fewer attempts leave
    cells empty; a single-column activity puts its value in the result column.
    """

    attempts: dict[str, str] = {}
    for group in groups:
        for entry in group.entries:
            if not entry.result:
                attempts.setdefault(_label_key(entry.sub), entry.sub)
    # Activities may name their result differently ("total", "nota"): the
    # column shows each name once.
    result_labels: dict[str, str] = {}
    for group in groups:
        for entry in group.entries:
            if entry.result and entry.sub:
                result_labels.setdefault(_label_key(entry.sub), _capitalized(entry.sub))
    result_label = " / ".join(result_labels.values())
    width = 2 + len(attempts)

    title_html = f"<tr>{_cell('th', title, TITLE_STYLE, colspan=width)}</tr>" if title else ""
    header_html = (
        f"<tr>{_cell('th', '', HEADER_STYLE)}"
        + "".join(_cell("th", _capitalized(label), HEADER_STYLE) for label in attempts.values())
        + f"{_cell('th', result_label, HEADER_STYLE)}</tr>"
    )
    rows = []
    for index, group in enumerate(groups):
        striped = index % 2 == 1
        by_attempt = {_label_key(entry.sub): entry for entry in group.entries if not entry.result}
        result = next((entry for entry in group.entries if entry.result), None)
        if len(group.entries) == 1 and not group.entries[0].sub:
            # A single-column activity: one empty cell across the attempts.
            gap = (
                f'<td colspan="{len(attempts)}" style="{_value_style("", striped)}"></td>' if len(attempts) > 1
                else _grid_cell(None, striped, False) * len(attempts)
            )
            cells = gap + _grid_cell(result, striped, False)
        else:
            cells = "".join(_grid_cell(by_attempt.get(key), striped, False) for key in attempts)
            cells += _grid_cell(result, striped, bool(attempts))
        rows.append(f"<tr>{_cell('th', group.label, ROW_HEADER_STYLE)}{cells}</tr>")
    return f"{TABLE_OPEN}<thead>{title_html}{header_html}</thead><tbody>{''.join(rows)}</tbody></table>"


def _render_two_row_header(groups: list[FeedbackGroup], title: str) -> str:
    """Activity labels spanning their columns, with each column's label below."""

    entries = [entry for group in groups for entry in group.entries]
    two_rows = any(group.spans for group in groups)
    top = "".join(
        _cell("th", group.label, HEADER_STYLE, colspan=len(group.entries) if len(group.entries) > 1 else None)
        if group.spans
        else _cell("th", group.label, HEADER_STYLE, rowspan=2 if two_rows else None)
        for group in groups
    )
    subs = "".join(
        _cell("th", _capitalized(entry.sub), SUBHEADER_STYLE)
        for group in groups
        if group.spans
        for entry in group.entries
    )
    title_html = f"<tr>{_cell('th', title, TITLE_STYLE, colspan=len(entries))}</tr>" if title else ""
    header_html = f"<tr>{top}</tr>" + (f"<tr>{subs}</tr>" if two_rows else "")
    # The result of an activity with several columns stands out in bold.
    values = "".join(
        _cell(
            "td",
            entry.value,
            _value_style(entry.value, False) + (f";{RESULT_STYLE}" if entry.result and len(group.entries) > 1 else ""),
        )
        for group in groups
        for entry in group.entries
    )
    footer_rows = [list(row) for row in zip(*(entry.footers for entry in entries))] if entries[0].footers else []
    footer_rows = [row for row in footer_rows if any(row)]
    footer_html = (
        "<tfoot>"
        + "".join(
            f"<tr>{_value_cells(row, striped=index % 2 == 0, small=True)}</tr>" for index, row in enumerate(footer_rows)
        )
        + "</tfoot>"
        if footer_rows
        else ""
    )
    return f"{TABLE_OPEN}<thead>{title_html}{header_html}</thead><tbody><tr>{values}</tr></tbody>{footer_html}</table>"


def render_grouped_table(groups: list[FeedbackGroup], title: str = "", layout: str = LAYOUT_HORIZONTAL) -> str:
    """Build the feedback table for one student of a sheet with a two-row header.

    The horizontal table keeps the sheet's two header rows; the vertical one
    is a grid with one row per activity and its attempts side by side.
    """

    groups = [group for group in groups if group.entries]
    if not groups:
        return ""
    if layout == LAYOUT_VERTICAL:
        return _render_grid(groups, title)
    return _render_two_row_header(groups, title)
