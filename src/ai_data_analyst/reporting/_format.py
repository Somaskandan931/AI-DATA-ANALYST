"""Text helpers shared by the report builder and its renderers.

Everything a report prints that came from the uploaded file (column names, group keys,
category values, the file name) is untrusted. The renderers escape it with these helpers;
nothing in a report is ever interpreted as markup, script or a link.
"""

from __future__ import annotations

import html
import math
import re
from typing import Final

_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_MARKDOWN_SPECIAL: Final = re.compile(r"([\\`*_\[\]<>|!#~&])")

MISSING: Final = "n/a"


def fmt_value(value: object) -> str:
    """Render a result value as text. ``None`` and non-finite numbers become ``n/a``.

    Operation results are already rounded to 6 decimals, so this prints them exactly (it does
    not round further); a number in a report is the number in its artifact.
    """
    if value is None:
        return MISSING
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return MISSING
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text
    return str(value)


def single_line(text: str) -> str:
    """Replace control characters (including newlines) with a space."""
    return _CONTROL.sub(" ", text)


def escape_html(text: object) -> str:
    """Escape for HTML text and attribute values."""
    return html.escape(single_line(str(text)), quote=True)


def escape_markdown(text: object) -> str:
    """Backslash-escape Markdown and raw-HTML metacharacters; the result is one line."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", single_line(str(text)))
