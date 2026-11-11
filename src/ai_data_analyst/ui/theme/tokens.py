"""Field Notes design tokens.

The palette is repeated in ``.streamlit/config.toml`` because TOML cannot import Python.
``tests/unit/test_ui_theme.py`` keeps the two copies in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Palette:
    """Calm editorial palette; decorative colours are not used for normal text."""

    canvas: str = "#F4F1E9"
    ink: str = "#202520"
    ink_muted: str = "#5B5F57"
    rule: str = "#D8D3C4"
    secondary_surface: str = "#EAE5D8"
    sage: str = "#75866A"
    sage_text: str = "#5E6E54"
    persimmon: str = "#D96845"
    persimmon_text: str = "#B04E2F"
    persimmon_deep: str = "#9B4429"
    sage_tint: str = "#E7EBE2"
    persimmon_tint: str = "#F6E4DC"
    on_persimmon: str = "#FFFFFF"
    chart_categorical: tuple[str, ...] = (
        "#5E6E54",
        "#B04E2F",
        "#6B7F8C",
        "#8C7A5B",
        "#7A6A86",
        "#4F6B5D",
        "#C07A5E",
        "#5B5F57",
    )


PALETTE: Final = Palette()


@dataclass(frozen=True)
class TypeScale:
    """Editorial type scale in rem."""

    xs: str = "0.75rem"
    sm: str = "0.875rem"
    base: str = "1rem"
    lg: str = "1.125rem"
    xl: str = "1.375rem"
    xxl: str = "1.75rem"
    xxxl: str = "2.25rem"
    display: str = "3rem"


TYPE_SCALE: Final = TypeScale()

SPACING: Final[dict[str, str]] = {
    "1": "0.25rem",
    "2": "0.5rem",
    "3": "0.75rem",
    "4": "1rem",
    "5": "1.5rem",
    "6": "2rem",
    "7": "3rem",
    "8": "4rem",
}

RULE_WEIGHT: Final = "1px"
RULE_WEIGHT_STRONG: Final = "2px"
PROSE_MAX_WIDTH: Final = "68ch"
RADIUS: Final = "2px"
MOTION_FAST: Final = "140ms"
MOTION_STANDARD: Final = "220ms"
MOTION_ARRIVAL: Final = "360ms"
MOTION_TAB: Final = "160ms"
MOTION_STAGGER: Final = "40ms"
EASING: Final = "cubic-bezier(0.22, 0.61, 0.36, 1)"

FONT_UI: Final = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_HEADING: Final = "'Fraunces', Georgia, 'Times New Roman', serif"
FONT_MONO: Final = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"

CLASSES: Final[dict[str, str]] = {
    "app_header": "fn-app-header",
    "app_wordmark": "fn-app-wordmark",
    "app_subtitle": "fn-app-subtitle",
    "page_header": "fn-page-header",
    "page_heading": "fn-page-heading",
    "page_title": "fn-page-title",
    "page_purpose": "fn-page-purpose",
    "section_label": "fn-section-label",
    "section_head": "fn-section-head",
    "evidence_card": "fn-evidence-card",
    "evidence_body": "fn-evidence-body",
    "evidence_value": "fn-evidence-value",
    "evidence_value_missing": "fn-evidence-value--missing",
    "evidence_label": "fn-evidence-label",
    "evidence_note": "fn-evidence-note",
    "card_grid": "fn-card-grid",
    "card_footer": "fn-card-footer",
    "computed_from": "fn-computed-from",
    "footnote": "fn-footnote",
    "source_chip": "fn-source-chip",
    "source_chip_computed": "fn-source-chip--computed",
    "source_chip_query_result": "fn-source-chip--query-result",
    "chip_shape": "fn-chip-shape",
    "rule": "fn-rule",
    "prose": "fn-prose",
    "highlight": "fn-highlight",
    "empty_hero": "fn-empty-hero",
    "wordmark": "fn-wordmark",
    "hero_title": "fn-hero-title",
    "hero_purpose": "fn-hero-purpose",
    "hero_steps": "fn-hero-steps",
    "intro": "fn-intro",
    "intro_marker": "fn-intro-marker",
    "result_marker": "fn-result-marker",
    "shell_marker": "fn-shell-marker",
    "fresh": "fn-fresh",
    "table_scroll": "fn-table-scroll",
    "table": "fn-table",
    "table_caption": "fn-table-caption",
    "table_num": "fn-num",
    "kv_figure": "fn-kv-figure",
    "kv_list": "fn-kv-list",
    "kv_item": "fn-kv-item",
    "kv_title": "fn-kv-title",
    "kv_pairs": "fn-kv-pairs",
    "kv_pair": "fn-kv-pair",
    "kv_values": "fn-kv-values",
    "inspector": "fn-inspector",
    "inspector_section": "fn-inspector-section",
    "inspector_title": "fn-inspector-title",
    "inspector_list": "fn-inspector-list",
    "inspector_row": "fn-inspector-row",
    "mono": "fn-mono",
    "fingerprint": "fn-fingerprint",
    "chart_marker": "fn-chart-marker",
}
