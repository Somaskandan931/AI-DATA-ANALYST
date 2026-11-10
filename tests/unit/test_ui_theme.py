"""Field Notes token, config, contrast, motion, and escaping checks."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from ai_data_analyst.ui.theme import (  # noqa: E402
    CLASSES,
    PALETTE,
    PROSE_MAX_WIDTH,
    SPACING,
    TYPE_SCALE,
    css,
)
from ai_data_analyst.ui.theme.html import escape_text  # noqa: E402
from ai_data_analyst.ui.theme.tokens import EASING  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".streamlit" / "config.toml"
PYPROJECT = ROOT / "pyproject.toml"


def _luminance(colour: str) -> float:
    red, green, blue = (int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5))
    channels = []
    for channel in (red, green, blue):
        low = channel / 12.92
        high = ((channel + 0.055) / 1.055) ** 2.4
        channels.append(low if channel <= 0.04045 else high)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_theme_colours_meet_contrast_targets() -> None:
    assert _contrast(PALETTE.ink, PALETTE.canvas) >= 7
    assert _contrast(PALETTE.ink_muted, PALETTE.canvas) >= 4.5
    assert _contrast(PALETTE.sage_text, PALETTE.canvas) >= 4.5
    assert _contrast(PALETTE.persimmon_text, PALETTE.canvas) >= 4.5
    assert _contrast(PALETTE.on_persimmon, PALETTE.persimmon_text) >= 4.5


def test_toml_palette_matches_tokens() -> None:
    theme = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]

    assert theme["backgroundColor"] == PALETTE.canvas
    assert theme["secondaryBackgroundColor"] == PALETTE.secondary_surface
    assert theme["textColor"] == PALETTE.ink
    assert theme["primaryColor"] == PALETTE.persimmon_text
    assert theme["borderColor"] == PALETTE.rule
    assert theme["chartCategoricalColors"] == list(PALETTE.chart_categorical)


def test_scales_and_class_vocabulary_are_explicit() -> None:
    assert TYPE_SCALE.display == "3rem"
    assert SPACING["8"] == "4rem"
    assert PROSE_MAX_WIDTH == "68ch"
    assert CLASSES == {
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
    }


def test_stylesheet_has_paper_grain_utilities_and_reduced_motion() -> None:
    stylesheet = css.build_css()

    assert "--fn-canvas: #F4F1E9" in stylesheet
    assert "radial-gradient" in stylesheet
    assert ".fn-app-header" in stylesheet
    assert ".fn-app-wordmark" in stylesheet
    assert ".fn-page-header" in stylesheet
    assert ".fn-section-label" in stylesheet
    assert ".fn-section-head" in stylesheet
    assert ".fn-evidence-card" in stylesheet
    assert ".fn-evidence-body" in stylesheet
    assert ".fn-card-footer" in stylesheet
    assert ".fn-source-chip" in stylesheet
    assert ".fn-rule" in stylesheet
    assert ".fn-prose" in stylesheet
    assert "68ch" in stylesheet
    assert ".fn-highlight" in stylesheet
    assert ".fn-fresh" in stylesheet
    assert ".fn-page-heading" in stylesheet
    assert ".fn-card-grid" in stylesheet
    assert ".fn-chip-shape" in stylesheet
    assert ".fn-footnote" in stylesheet
    assert ".fn-computed-from" in stylesheet
    assert ".fn-hero-steps" in stylesheet
    assert ".fn-result-marker" in stylesheet
    assert ":has(.fn-shell-marker)" in stylesheet
    assert "flex-direction: column-reverse" in stylesheet
    assert "@media (prefers-reduced-motion: reduce)" in stylesheet
    assert "animation: none" in stylesheet


def _block(stylesheet: str, opener: str) -> str:
    """Return *opener* and its balanced braces, so nested rules stay intact."""
    start = stylesheet.index(opener)
    depth = 0
    for index in range(start, len(stylesheet)):
        if stylesheet[index] == "{":
            depth += 1
        elif stylesheet[index] == "}":
            depth -= 1
            if depth == 0:
                return stylesheet[start : index + 1]
    raise AssertionError(f"unbalanced CSS block for {opener!r}")


def _declarations(stylesheet: str, properties: str) -> list[str]:
    pattern = rf"(?<![\w-]){properties}\s*:\s*([^;]+);"
    return [value.strip() for value in re.findall(pattern, stylesheet)]


def test_one_shared_easing_token_and_tokenised_durations() -> None:
    stylesheet = css.build_css()

    assert stylesheet.count("cubic-bezier(") == 1
    assert f"--fn-ease: {EASING};" in stylesheet
    for value in _declarations(stylesheet, r"(?:animation|transition)"):
        if value.split()[0] == "none":
            continue
        assert "var(--fn-ease)" in value, value
        assert "var(--fn-motion-" in value, value
        # A literal millisecond value would silently drift from the token set.
        assert not re.search(r"\b\d+(?:\.\d+)?m?s\b", value), value
    for value in _declarations(stylesheet, r"(?:animation|transition)-(?:duration|delay)"):
        assert "var(--fn-motion-" in value, value
        assert not re.search(r"\b\d+(?:\.\d+)?m?s\b", value), value
    for value in _declarations(stylesheet, "animation-timing-function"):
        assert value == "var(--fn-ease)", value


def test_keyframes_animate_only_compositor_properties() -> None:
    stylesheet = css.build_css()
    names = re.findall(r"@keyframes\s+([\w-]+)", stylesheet)
    assert names

    for name in names:
        block = _block(stylesheet, f"@keyframes {name}")
        properties = set(re.findall(r"([\w-]+)\s*:", block))
        assert properties <= {"opacity", "transform", "background-size"}, (name, properties)


def test_transitions_avoid_layout_properties() -> None:
    stylesheet = css.build_css()
    allowed = {"opacity", "transform", "background-size", "clip-path", "content-visibility"}

    for value in _declarations(stylesheet, "transition"):
        if value == "none" or "!important" in value:
            continue
        for part in value.split(","):
            property_name = part.split()[0]
            assert property_name in allowed, part


def test_view_timelines_live_inside_supports_with_visible_default() -> None:
    stylesheet = css.build_css()
    supported = _block(stylesheet, "@supports (animation-timeline: view())")

    assert supported.count("animation-timeline: view();") == 3
    assert "prefers-reduced-motion: no-preference" in supported
    # The unanimated default must be the final, fully visible state.
    assert "opacity:" not in supported
    outside = stylesheet.replace(supported, "", 1)
    assert "animation-timeline: view()" not in outside


def test_every_keyframe_is_used_and_reduced_motion_disables_motion() -> None:
    stylesheet = css.build_css()
    names = re.findall(r"@keyframes\s+([\w-]+)", stylesheet)
    for name in names:
        assert stylesheet.count(name) > 1, f"{name} is declared but never applied"

    reduce_block = _block(stylesheet, "@media (prefers-reduced-motion: reduce)")
    assert "*," in reduce_block
    assert "*::before," in reduce_block
    assert "*::after" in reduce_block
    assert "animation: none !important;" in reduce_block
    assert "transition: none !important;" in reduce_block
    assert "scroll-behavior: auto !important;" in reduce_block


def test_fresh_content_keeps_one_time_based_arrival() -> None:
    stylesheet = css.build_css()

    assert ".fn-fresh {" in stylesheet
    assert "animation: fn-rise-in var(--fn-motion-arrival)" in stylesheet
    # The inner scroll reveal must not double up on freshly rendered content.
    fresh_block = _block(stylesheet, ".fn-fresh {")
    assert "animation" in fresh_block
    assert ".fn-fresh .fn-evidence-body" in stylesheet
    assert '.fn-fresh [data-testid="stExpander"]' in stylesheet
    fresh_override = _block(stylesheet, ".fn-fresh .fn-evidence-body")
    assert "animation: none" in fresh_override


def test_streamlit_floor_is_166() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = project["project"]["optional-dependencies"]["app"]

    assert any(
        dependency.replace(" ", "").startswith("streamlit>=1.66") for dependency in dependencies
    )


def test_escape_text_neutralises_hostile_strings() -> None:
    payload = '<script>alert("x")</script>'

    escaped = escape_text(payload)

    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert "&quot;" in escaped


def test_fresh_class_only_marks_changed_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(css.st, "session_state", {})

    assert css.fresh_class("hero", None) == "fn-fresh"
    assert css.fresh_class("hero", None) == ""
    assert css.fresh_class("hero", "new") == "fn-fresh"
