"""Render the per-student feedback table stored in Moodle's feedback comments.

Moodle saves imported feedback comments as HTML and styles tables with
Bootstrap, so the built-in table classes give the borders and spacing. Colours
and alignment are inline styles on each cell: Moodle keeps them, and they do
not depend on the theme. The look follows the teachers' grades sheets: green
header cells with white text, light green stripes, and failing grades and
"NP" (no presentat) in red.
The HTML is kept on a single line so the CSV cell stays simple.
"""

from html import escape

from gradeskit.tabular import parse_number

LAYOUT_HORIZONTAL = "horizontal"
LAYOUT_VERTICAL = "vertical"
TABLE_OPEN = '<table class="table table-sm table-bordered">'
PASS_GRADE = 5
# Marks shown in red like a failing grade, compared without case.
FAIL_MARKS = {"NP"}

CENTER = "text-align:center;vertical-align:middle"
TITLE_STYLE = f"{CENTER};background-color:#38761d;color:#ffffff;font-weight:bold"
HEADER_STYLE = f"{CENTER};background-color:#6aa84f;color:#ffffff;font-weight:bold"
STRIPE_BACKGROUND = "background-color:#d9ead3"
FAIL_STYLE = "color:#e00000"


def _value_style(value: str, striped: bool) -> str:
    """Centre a value, shade striped rows and show numbers under 5 and NP in red."""

    parts = [CENTER]
    if striped:
        parts.append(STRIPE_BACKGROUND)
    number = parse_number(value)
    if (number is not None and number < PASS_GRADE) or value.strip().upper() in FAIL_MARKS:
        parts.append(FAIL_STYLE)
    return ";".join(parts)


def _cell(tag: str, value: str, style: str, small: bool = False, colspan: int | None = None) -> str:
    text = f"<small>{escape(value)}</small>" if small else escape(value)
    span = f' colspan="{colspan}"' if colspan else ""
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
            f"<tr>{_cell('th', header, HEADER_STYLE)}"
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
