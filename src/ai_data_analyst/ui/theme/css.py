"""The single source of Field Notes CSS and the per-run motion helper."""

from __future__ import annotations

from string import Template

import streamlit as st

from .tokens import (
    CLASSES,
    FONT_HEADING,
    FONT_MONO,
    FONT_UI,
    MOTION_DURATION,
    PALETTE,
    PROSE_MAX_WIDTH,
    RADIUS,
    RULE_WEIGHT,
    RULE_WEIGHT_STRONG,
    SPACING,
    TYPE_SCALE,
)

_FRESH_KEY = "fn_fresh_tokens"

_CSS_TEMPLATE = Template(
    """
:root {
    --fn-canvas: $canvas;
    --fn-ink: $ink;
    --fn-ink-muted: $ink_muted;
    --fn-rule: $rule;
    --fn-rule-weight: $rule_weight;
    --fn-rule-weight-strong: $rule_weight_strong;
    --fn-secondary-surface: $secondary_surface;
    --fn-sage: $sage;
    --fn-sage-text: $sage_text;
    --fn-persimmon: $persimmon;
    --fn-persimmon-text: $persimmon_text;
    --fn-on-persimmon: $on_persimmon;
    --fn-font-ui: $font_ui;
    --fn-font-heading: $font_heading;
    --fn-font-mono: $font_mono;
    --fn-text-xs: $text_xs;
    --fn-text-sm: $text_sm;
    --fn-text-base: $text_base;
    --fn-text-lg: $text_lg;
    --fn-text-xl: $text_xl;
    --fn-text-xxl: $text_xxl;
    --fn-text-xxxl: $text_xxxl;
    --fn-text-display: $text_display;
    --fn-space-1: $space_1;
    --fn-space-2: $space_2;
    --fn-space-3: $space_3;
    --fn-space-4: $space_4;
    --fn-space-5: $space_5;
    --fn-space-6: $space_6;
    --fn-space-7: $space_7;
    --fn-space-8: $space_8;
    --fn-prose: $prose;
    --fn-radius: $radius;
    --fn-motion-duration: $motion_duration;
}

html,
body,
[data-testid="stAppViewContainer"] {
    background-color: var(--fn-canvas);
    color: var(--fn-ink);
    font-family: var(--fn-font-ui);
}

[data-testid="stAppViewContainer"] {
    background-image:
        radial-gradient(circle at 18% 24%, rgba(32, 37, 32, 0.022) 0 0.55px, transparent 0.8px),
        radial-gradient(circle at 72% 68%, rgba(32, 37, 32, 0.018) 0 0.65px, transparent 0.9px);
    background-size: 9px 9px, 13px 13px;
}

h1,
h2,
h3,
h4,
h5,
h6,
[data-testid="stHeading"] {
    font-family: var(--fn-font-heading);
    letter-spacing: -0.015em;
}

code,
pre,
[data-testid="stCode"] {
    font-family: var(--fn-font-mono);
}

:where(a, button, input, textarea, select, summary, [tabindex]):focus-visible {
    outline: 2px solid var(--fn-persimmon-text);
    outline-offset: 2px;
}

.fn-page-header {
    max-width: var(--fn-prose);
    margin: 0 0 var(--fn-space-4);
    font-family: var(--fn-font-heading);
    font-size: var(--fn-text-xxxl);
    font-weight: 500;
    line-height: 1.08;
}

.fn-section-label {
    margin: var(--fn-space-5) 0 var(--fn-space-2);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.fn-rule {
    border: 0;
    border-top: var(--fn-rule-weight) solid var(--fn-rule);
    margin: var(--fn-space-4) 0;
}

.fn-evidence-card {
    max-width: var(--fn-prose);
    border-top: var(--fn-rule-weight-strong) solid var(--fn-ink);
    padding: var(--fn-space-3) 0 var(--fn-space-4);
}

.fn-evidence-value {
    color: var(--fn-ink);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xxl);
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
}

.fn-evidence-label {
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.fn-evidence-note {
    max-width: var(--fn-prose);
    color: var(--fn-ink-muted);
    font-size: var(--fn-text-sm);
    line-height: 1.55;
}

.fn-source-chip {
    display: inline-block;
    padding: 0.1rem 0.38rem;
    border: var(--fn-rule-weight) solid var(--fn-rule);
    border-radius: var(--fn-radius);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.08em;
    line-height: 1.4;
    text-transform: uppercase;
    white-space: nowrap;
}

.fn-source-chip--computed {
    border-color: var(--fn-sage-text);
    color: var(--fn-sage-text);
}

.fn-source-chip--query-result {
    border-color: var(--fn-persimmon-text);
    color: var(--fn-persimmon-text);
}

.fn-source-chip--ai-explanation {
    border-color: var(--fn-ink);
    color: var(--fn-ink);
}

.fn-source-chip--unavailable {
    border-style: dashed;
    color: var(--fn-ink-muted);
}

.fn-prose {
    max-width: var(--fn-prose);
    font-size: var(--fn-text-base);
    line-height: 1.6;
}

.fn-highlight {
    background-image: linear-gradient(
        180deg,
        transparent 58%,
        rgba(217, 104, 69, 0.22) 58%,
        rgba(217, 104, 69, 0.22) 90%,
        transparent 90%
    );
    background-repeat: no-repeat;
}

.fn-empty-hero {
    max-width: var(--fn-prose);
    padding: var(--fn-space-7) 0 var(--fn-space-5);
    border-bottom: var(--fn-rule-weight) solid var(--fn-rule);
}

.fn-wordmark {
    margin: 0 0 var(--fn-space-5);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.16em;
    text-transform: uppercase;
}

.fn-hero-title {
    max-width: 18ch;
    margin: 0 0 var(--fn-space-3);
    font-family: var(--fn-font-heading);
    font-size: var(--fn-text-display);
    font-weight: 500;
    line-height: 1.02;
}

.fn-hero-purpose {
    max-width: var(--fn-prose);
    margin: 0;
    color: var(--fn-ink-muted);
    font-size: var(--fn-text-lg);
    line-height: 1.55;
}

@keyframes fn-rise {
    from {
        opacity: 0;
        transform: translateY(6px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.fn-fresh {
    animation: fn-rise var(--fn-motion-duration) ease-out both;
}

@media (prefers-reduced-motion: reduce) {
    .fn-fresh {
        animation: none;
    }
}
"""
)


def build_css() -> str:
    """Return the complete Field Notes stylesheet."""
    return _CSS_TEMPLATE.substitute(
        canvas=PALETTE.canvas,
        ink=PALETTE.ink,
        ink_muted=PALETTE.ink_muted,
        rule=PALETTE.rule,
        rule_weight=RULE_WEIGHT,
        rule_weight_strong=RULE_WEIGHT_STRONG,
        secondary_surface=PALETTE.secondary_surface,
        sage=PALETTE.sage,
        sage_text=PALETTE.sage_text,
        persimmon=PALETTE.persimmon,
        persimmon_text=PALETTE.persimmon_text,
        on_persimmon=PALETTE.on_persimmon,
        font_ui=FONT_UI,
        font_heading=FONT_HEADING,
        font_mono=FONT_MONO,
        text_xs=TYPE_SCALE.xs,
        text_sm=TYPE_SCALE.sm,
        text_base=TYPE_SCALE.base,
        text_lg=TYPE_SCALE.lg,
        text_xl=TYPE_SCALE.xl,
        text_xxl=TYPE_SCALE.xxl,
        text_xxxl=TYPE_SCALE.xxxl,
        text_display=TYPE_SCALE.display,
        space_1=SPACING["1"],
        space_2=SPACING["2"],
        space_3=SPACING["3"],
        space_4=SPACING["4"],
        space_5=SPACING["5"],
        space_6=SPACING["6"],
        space_7=SPACING["7"],
        space_8=SPACING["8"],
        prose=PROSE_MAX_WIDTH,
        radius=RADIUS,
        motion_duration=MOTION_DURATION,
    )


def apply_theme() -> None:
    """Inject the one app-wide stylesheet. Static CSS only; never interpolate data."""
    st.markdown(f"<style>{build_css()}</style>", unsafe_allow_html=True)


def fresh_class(key: str, token: object = None) -> str:
    """Return the fresh class only when *token* changed since the previous rerun."""
    stored = st.session_state.get(_FRESH_KEY)
    seen = dict(stored) if isinstance(stored, dict) else {}
    marker = repr(token)
    is_fresh = seen.get(key) != marker
    seen[key] = marker
    st.session_state[_FRESH_KEY] = seen
    return CLASSES["fresh"] if is_fresh else ""
