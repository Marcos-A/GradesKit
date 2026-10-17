"""Render the per-student feedback table stored in Moodle's feedback comments.

Moodle saves imported feedback comments as HTML and styles tables with
Bootstrap, so the built-in table classes are enough. The HTML is kept on a
single line so the CSV cell stays simple.
"""

from html import escape

LAYOUT_HORIZONTAL = "horizontal"
LAYOUT_VERTICAL = "vertical"
TABLE_OPEN = '<table class="table table-sm table-bordered">'


def _cells(tag: str, values: list[str], small: bool = False) -> str:
    if small:
        return "".join(f"<{tag}><small>{escape(value)}</small></{tag}>" for value in values)
    return "".join(f"<{tag}>{escape(value)}</{tag}>" for value in values)


def render_feedback_table(
    headers: list[str],
    values: list[str],
    footer_rows: list[list[str]],
    title: str = "",
    layout: str = LAYOUT_HORIZONTAL,
) -> str:
    """Build the feedback table for one student.

    `footer_rows` hold extra rows from the sheet such as weights ("50%"); rows
    that are empty for the chosen columns are left out.
    """

    if not headers:
        return ""
    footer_rows = [row for row in footer_rows if any(row)]

    if layout == LAYOUT_VERTICAL:
        width = 2 + len(footer_rows)
        title_html = f'<thead><tr><th colspan="{width}">{escape(title)}</th></tr></thead>' if title else ""
        body = "".join(
            f"<tr><th>{escape(header)}</th><td>{escape(value)}</td>"
            + _cells("td", [row[index] for row in footer_rows], small=True)
            + "</tr>"
            for index, (header, value) in enumerate(zip(headers, values))
        )
        return f"{TABLE_OPEN}{title_html}<tbody>{body}</tbody></table>"

    title_html = f'<tr><th colspan="{len(headers)}">{escape(title)}</th></tr>' if title else ""
    footer_html = (
        "<tfoot>" + "".join(f"<tr>{_cells('td', row, small=True)}</tr>" for row in footer_rows) + "</tfoot>"
        if footer_rows
        else ""
    )
    return (
        f"{TABLE_OPEN}<thead>{title_html}<tr>{_cells('th', headers)}</tr></thead>"
        f"<tbody><tr>{_cells('td', values)}</tr></tbody>{footer_html}</table>"
    )
