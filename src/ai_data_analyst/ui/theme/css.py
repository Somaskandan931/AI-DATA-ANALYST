"""The single source of Field Notes CSS, its small interaction script and motion helpers.

Part A rules are static. Part B motion follows one contract: only opacity, transform,
clip-path and background-size move; scroll-driven reveals are gated behind
``@supports (animation-timeline: view())`` with a fully visible default; time-based
motion is limited to a freshly produced result, the once-per-session hero intro, tab
panels and the loading line. Everything is disabled under ``prefers-reduced-motion``.
"""

from __future__ import annotations

from string import Template

import streamlit as st

from .tokens import (
    CLASSES,
    EASING,
    FONT_HEADING,
    FONT_MONO,
    FONT_UI,
    MOTION_ARRIVAL,
    MOTION_FAST,
    MOTION_STAGGER,
    MOTION_STANDARD,
    MOTION_TAB,
    PALETTE,
    PROSE_MAX_WIDTH,
    RADIUS,
    RULE_WEIGHT,
    RULE_WEIGHT_STRONG,
    SPACING,
    TYPE_SCALE,
)

_FRESH_KEY = "fn_fresh_tokens"

# A static inline SVG mask for the quiet replace action; no data is interpolated into it.
_REPLACE_ICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
    "%3Cpath d='M13 8a5 5 0 1 1-1.5-3.5M13 2v3h-3' fill='none' stroke='black' "
    "stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"
)

# A delegated listener is injected once per document; it never runs on a rerun twice.
_INTERACTION_SCRIPT = """
<span class="fn-script-anchor" hidden></span>
<script>
(() => {
    if (window.__fnEvidenceHandlers) { return; }
    window.__fnEvidenceHandlers = true;
    const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.addEventListener("click", (event) => {
        const node = event.target instanceof Element ? event.target : null;
        const link = node ? node.closest(".fn-footnote a[href^='#']") : null;
        if (!link) { return; }
        const target = document.getElementById(
            decodeURIComponent(link.getAttribute("href").slice(1))
        );
        if (!target || target.tagName.toLowerCase() !== "details") { return; }
        if (!target.classList.contains("fn-computed-from")) { return; }
        event.preventDefault();
        target.open = true;
        target.classList.remove("fn-pulse");
        void target.offsetWidth;
        target.classList.add("fn-pulse");
        window.setTimeout(() => target.classList.remove("fn-pulse"), 900);
        target.scrollIntoView({
            behavior: reduced() ? "auto" : "smooth",
            block: "center",
            inline: "nearest",
        });
    }, true);
})();
</script>
"""

_CSS_TEMPLATE = Template(
    """
:root {
    --fn-canvas: $canvas;
    --fn-ink: $ink;
    --fn-ink-muted: $ink_muted;
    --fn-rule: $rule;
    --fn-rule-weight: $rule_weight;
    --fn-rule-weight-strong: $rule_weight_strong;
    --fn-card-rule-weight: $rule_weight_strong;
    --fn-secondary-surface: $secondary_surface;
    --fn-sage: $sage;
    --fn-sage-text: $sage_text;
    --fn-sage-tint: $sage_tint;
    --fn-persimmon: $persimmon;
    --fn-persimmon-text: $persimmon_text;
    --fn-persimmon-deep: $persimmon_deep;
    --fn-persimmon-tint: $persimmon_tint;
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
    --fn-motion-fast: $motion_fast;
    --fn-motion-standard: $motion_standard;
    --fn-motion-arrival: $motion_arrival;
    --fn-motion-tab: $motion_tab;
    --fn-motion-stagger: $motion_stagger;
    --fn-ease: $easing;
}

/* ---- canvas ------------------------------------------------------------------------- */

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

[data-testid="stMainBlockContainer"],
.block-container {
    max-width: 1180px;
    padding-top: 1.25rem !important;
    padding-bottom: var(--fn-space-8) !important;
}

[data-testid="stHeader"] {
    background: transparent;
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

/* Streamlit adds copy-link anchors next to markdown headings; the editorial
   headings below carry their own hierarchy, so the anchors stay out of the way. */
[data-testid="stHeaderActionElements"] {
    display: none !important;
}

@media (prefers-reduced-motion: no-preference) {
    html {
        scroll-behavior: smooth;
    }
}

/* ---- masthead ----------------------------------------------------------------------- */

.fn-app-header {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.15rem var(--fn-space-3);
    margin: 0 0 var(--fn-space-3);
    padding: 0 0 var(--fn-space-2);
    border-bottom: var(--fn-rule-weight) solid var(--fn-rule);
}

.fn-app-wordmark {
    margin: 0;
    font-family: var(--fn-font-heading);
    font-size: 1.75rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    line-height: 1.1;
}

.fn-app-subtitle {
    margin: 0;
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.04em;
    line-height: 1.4;
}

/* ---- editorial headings ------------------------------------------------------------- */

.fn-page-header {
    max-width: var(--fn-prose);
    margin: 0 0 var(--fn-space-4);
    font-family: var(--fn-font-heading);
    font-size: var(--fn-text-xxxl);
    font-weight: 500;
    line-height: 1.08;
}

.fn-page-heading {
    max-width: var(--fn-prose);
    margin: 0 0 var(--fn-space-5);
}

.fn-page-title {
    margin: 0 0 var(--fn-space-2);
    font-family: var(--fn-font-heading);
    font-size: var(--fn-text-xxxl);
    font-weight: 500;
    letter-spacing: -0.015em;
    line-height: 1.08;
}

.fn-page-purpose {
    margin: 0;
    color: var(--fn-ink-muted);
    font-size: var(--fn-text-lg);
    line-height: 1.55;
}

.fn-section-head {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: var(--fn-space-3);
    margin: var(--fn-space-5) 0 var(--fn-space-2);
}

.fn-section-label {
    margin: var(--fn-space-5) 0 var(--fn-space-2);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.fn-section-head .fn-section-label {
    margin: 0;
}

.fn-section-head .fn-source-chip {
    margin: 0;
}

.fn-rule {
    border: 0;
    border-top: var(--fn-rule-weight) solid var(--fn-rule);
    margin: var(--fn-space-4) 0;
}

/* ---- evidence cards ----------------------------------------------------------------- */

.fn-card-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--fn-space-4);
    margin: var(--fn-space-3) 0 var(--fn-space-5);
    align-items: stretch;
}

@media (max-width: 1100px) {
    .fn-card-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

.fn-evidence-card {
    position: relative;
    max-width: var(--fn-prose);
    border-top: 0;
    padding: calc(var(--fn-space-3) + var(--fn-card-rule-weight)) 0 var(--fn-space-4);
}

/* The ink rule is a pseudo-element so it can draw with a transform without moving
   any content; it stays fully drawn when scroll timelines are unavailable. */
.fn-evidence-card::before {
    content: "";
    position: absolute;
    top: 0;
    right: 0;
    left: 0;
    height: var(--fn-card-rule-weight);
    background: var(--fn-ink);
    transform: scaleX(1);
    transform-origin: left center;
}

.fn-card-grid > .fn-evidence-card {
    height: 100%;
    margin: 0;
    max-width: none;
}

.fn-evidence-body {
    display: flex;
    flex-direction: column;
    height: 100%;
}

.fn-evidence-value {
    margin: 0 0 var(--fn-space-1);
    color: var(--fn-ink);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xxl);
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
}

.fn-evidence-value--missing {
    color: var(--fn-ink-muted);
}

.fn-evidence-label {
    margin: 0 0 var(--fn-space-2);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.fn-evidence-note {
    margin: 0 0 var(--fn-space-3);
    max-width: var(--fn-prose);
    color: var(--fn-ink-muted);
    font-size: var(--fn-text-sm);
    line-height: 1.55;
}

/* Pinning the footer with margin-top:auto keeps every card's chip and provenance
   flush to the bottom, whatever length the interpretation happens to have. */
.fn-card-footer {
    margin-top: auto;
    padding-top: var(--fn-space-2);
}

.fn-card-footer .fn-source-chip {
    margin: 0 0 var(--fn-space-2);
}

.fn-card-footer .fn-computed-from {
    margin-top: 0;
}

.fn-source-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    margin: 0 0 var(--fn-space-2);
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

.fn-chip-shape {
    display: inline-block;
    width: 0.42rem;
    height: 0.42rem;
    border: 1px solid currentColor;
}

.fn-source-chip--computed .fn-chip-shape {
    background: currentColor;
}

.fn-source-chip--query-result .fn-chip-shape {
    transform: rotate(45deg);
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
    background-position: left bottom;
    background-size: 100% 100%;
}

.fn-footnote {
    margin-left: 0.1rem;
    font-size: var(--fn-text-xs);
    line-height: 0;
}

.fn-footnote a {
    color: var(--fn-persimmon-text);
    font-family: var(--fn-font-mono);
    text-decoration: none;
}

.fn-footnote:hover a,
.fn-footnote a:focus-visible {
    color: var(--fn-ink);
    text-decoration: underline;
}

.fn-evidence-card:has(.fn-footnote:hover) .fn-computed-from dl,
.fn-evidence-card:has(.fn-footnote a:focus-visible) .fn-computed-from dl {
    background: var(--fn-sage-tint);
    box-shadow: inset var(--fn-rule-weight-strong) 0 0 var(--fn-sage-text);
}

/* ---- computed from ------------------------------------------------------------------ */

.fn-computed-from {
    position: relative;
    isolation: isolate;
    margin-top: var(--fn-space-3);
    border-top: var(--fn-rule-weight) solid var(--fn-rule);
    padding-top: var(--fn-space-2);
}

.fn-computed-from summary {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    cursor: pointer;
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.08em;
    list-style: none;
    text-transform: uppercase;
}

.fn-computed-from summary::-webkit-details-marker {
    display: none;
}

.fn-computed-from summary::after {
    content: "";
    width: 0.35rem;
    height: 0.35rem;
    border-right: 1px solid currentColor;
    border-bottom: 1px solid currentColor;
    transform: rotate(-45deg);
    transform-origin: center;
    transition: transform var(--fn-motion-fast) var(--fn-ease);
}

.fn-computed-from[open] summary::after {
    transform: rotate(45deg);
}

.fn-computed-from summary:hover {
    color: var(--fn-ink);
}

.fn-computed-from dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.15rem 0.6rem;
    margin: var(--fn-space-2) 0 0;
    padding-left: var(--fn-space-2);
    box-shadow: inset var(--fn-rule-weight-strong) 0 0 transparent;
    font-size: var(--fn-text-sm);
}

.fn-computed-from dt {
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
}

.fn-computed-from dd {
    min-width: 0;
    margin: 0;
    overflow-wrap: anywhere;
}

/* A card is narrow; two columns would squeeze the value to one character per
   line, so the overview stacks each name above its value instead. */
.fn-card-grid .fn-computed-from dl {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
}

.fn-card-grid .fn-computed-from dd {
    margin: 0 0 var(--fn-space-2);
}

/* A thin tint pulse, painted under the text, marks the row a footnote opens. */
.fn-computed-from::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    background: var(--fn-persimmon-tint);
    opacity: 0;
    pointer-events: none;
}

@supports selector(::details-content) {
    .fn-computed-from::details-content {
        content-visibility: hidden;
        opacity: 0;
        transform: translateY(-2px);
        transition:
            content-visibility var(--fn-motion-standard) allow-discrete,
            opacity var(--fn-motion-standard) var(--fn-ease),
            transform var(--fn-motion-standard) var(--fn-ease);
    }

    .fn-computed-from[open]::details-content {
        content-visibility: visible;
        opacity: 1;
        transform: translateY(0);
    }
}

/* ---- data tables -------------------------------------------------------------------- */

/* The wrapper scrolls, never clips: a full header or value simply moves into reach.
   The two opaque covers are attached to the local content and hide the two edge
   shadows until the table actually overflows. */
.fn-table-scroll {
    max-width: 100%;
    margin: var(--fn-space-2) 0 var(--fn-space-4);
    overflow-x: auto;
    background:
        linear-gradient(to right, var(--fn-canvas) 30%, transparent) left center / 2.5rem
            100% no-repeat local,
        linear-gradient(to left, var(--fn-canvas) 30%, transparent) right center / 2.5rem
            100% no-repeat local,
        radial-gradient(farthest-side at 0 50%, rgba(32, 37, 32, 0.16), transparent) left
            center / 0.9rem 100% no-repeat scroll,
        radial-gradient(farthest-side at 100% 50%, rgba(32, 37, 32, 0.16), transparent) right
            center / 0.9rem 100% no-repeat scroll;
    background-attachment: local, local, scroll, scroll;
}

.fn-table {
    width: max-content;
    min-width: 100%;
    border-collapse: collapse;
    font-size: var(--fn-text-sm);
    font-variant-numeric: tabular-nums;
}

.fn-table-caption {
    padding: 0 0 var(--fn-space-2);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.04em;
    text-align: left;
}

.fn-table th,
.fn-table td {
    padding: var(--fn-space-2) var(--fn-space-3);
    border-bottom: var(--fn-rule-weight) solid var(--fn-rule);
    text-align: left;
    vertical-align: baseline;
    white-space: nowrap;
}

.fn-table tr > :first-child {
    padding-inline-start: 0;
}

.fn-table tr > :last-child {
    padding-inline-end: 0;
}

.fn-table thead th {
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.fn-table tbody th {
    font-weight: 500;
}

.fn-table .fn-num {
    text-align: right;
}

/* The first column stays in view while the rest scrolls; an opaque background keeps
   the moving cells from showing through it. */
.fn-table thead th:first-child,
.fn-table tbody th {
    position: sticky;
    left: 0;
    z-index: 1;
    background: var(--fn-canvas);
}

.fn-table thead th:first-child {
    z-index: 2;
}

/* ---- stacked key/value list --------------------------------------------------------- */

.fn-kv-figure {
    margin: var(--fn-space-2) 0 var(--fn-space-4);
}

.fn-kv-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: var(--fn-space-3) var(--fn-space-4);
}

.fn-kv-item {
    min-width: 0;
    border-top: var(--fn-rule-weight) solid var(--fn-rule);
    padding-top: var(--fn-space-2);
}

.fn-kv-title {
    margin: 0 0 var(--fn-space-1);
    font-weight: 500;
    overflow-wrap: anywhere;
}

.fn-kv-pairs {
    margin: 0;
}

.fn-kv-pair {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--fn-space-2);
    padding: 0.1rem 0;
}

.fn-kv-pair dt {
    min-width: 0;
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    overflow-wrap: anywhere;
}

.fn-kv-pair dd {
    flex: none;
    margin: 0;
    font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere;
    text-align: right;
}

.fn-kv-values {
    margin: 0;
    padding-inline-start: var(--fn-space-4);
}

@media (max-width: 480px) {
    .fn-kv-list {
        grid-template-columns: minmax(0, 1fr);
    }

    .fn-kv-pair {
        align-items: flex-start;
    }
}

/* ---- inspector ---------------------------------------------------------------------- */

/* The rail is about 240px wide, so every field stacks its label above a wrapping
   value; there is no table and nothing scrolls sideways. */
.fn-inspector {
    max-width: 100%;
}

.fn-inspector-section {
    margin: 0 0 var(--fn-space-4);
}

.fn-inspector-section:last-child {
    margin-bottom: 0;
}

.fn-inspector-title {
    margin: 0 0 var(--fn-space-1);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

.fn-inspector-list {
    margin: 0;
}

.fn-inspector-row {
    padding: var(--fn-space-1) 0;
    border-top: var(--fn-rule-weight) solid var(--fn-rule);
}

.fn-inspector-row:first-child {
    padding-top: 0;
    border-top: 0;
}

.fn-inspector-row dt {
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.04em;
    overflow-wrap: anywhere;
}

.fn-inspector-row dd {
    margin: 0.1rem 0 0;
    font-size: var(--fn-text-sm);
    line-height: 1.45;
    overflow-wrap: anywhere;
}

.fn-mono,
.fn-fingerprint {
    font-family: var(--fn-font-mono);
}

.fn-fingerprint {
    font-size: var(--fn-text-xs);
    letter-spacing: 0.04em;
}

.fn-inspector .fn-computed-from {
    margin-top: var(--fn-space-2);
}

.fn-inspector .fn-computed-from dl {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
}

.fn-inspector .fn-computed-from dd {
    margin: 0;
}

/* ---- empty state -------------------------------------------------------------------- */

.fn-empty-hero {
    max-width: var(--fn-prose);
    padding: var(--fn-space-5) 0 var(--fn-space-4);
    border-bottom: var(--fn-rule-weight) solid var(--fn-rule);
}

.fn-wordmark {
    margin: 0 0 var(--fn-space-4);
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

.fn-hero-steps {
    display: flex;
    flex-wrap: wrap;
    margin: var(--fn-space-5) 0 0;
    padding: var(--fn-space-2) 0;
    padding-inline: 0;
    border-top: var(--fn-rule-weight) solid var(--fn-rule);
    list-style: none;
}

.fn-hero-steps li {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    padding: 0 var(--fn-space-3);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.fn-hero-steps li:first-child {
    padding-inline-start: 0;
}

/* Streamlit's markdown list rule outranks a single class, so the hero adds one
   more class to keep the note flush with the headline. */
.fn-empty-hero .fn-hero-steps {
    padding-inline: 0;
}

.fn-empty-hero .fn-hero-steps li:first-child {
    padding-inline-start: 0;
}

.fn-hero-steps li + li {
    border-left: var(--fn-rule-weight) solid var(--fn-rule);
}

.fn-hero-steps li span {
    color: var(--fn-persimmon-text);
    font-size: 0.7rem;
    letter-spacing: 0.08em;
}

/* ---- shell --------------------------------------------------------------------------- */

.fn-shell-marker,
.fn-result-marker,
.fn-script-anchor {
    display: none;
}

@media (max-width: 640px) {
    [data-testid="stHorizontalBlock"]:has(.fn-shell-marker) {
        flex-direction: column-reverse;
    }
}

/* ---- native widgets ------------------------------------------------------------------ */

[data-testid="stAlertContainer"] {
    border: var(--fn-rule-weight) solid var(--fn-rule);
    border-left: 3px solid var(--fn-ink-muted);
    border-radius: 0;
    background: var(--fn-secondary-surface);
    color: var(--fn-ink);
    padding: var(--fn-space-3) var(--fn-space-4);
}

[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]),
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
    background: var(--fn-sage-tint);
    border-left-color: var(--fn-sage-text);
}

[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]),
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
    background: var(--fn-persimmon-tint);
    border-left-color: var(--fn-persimmon-text);
}

[data-testid="stAlertContainer"] * {
    color: inherit;
}

[data-testid="stAlertContainer"] a {
    text-decoration: underline;
}

[data-testid="stBaseButton-primary"] {
    border-radius: var(--fn-radius) !important;
    transition: transform var(--fn-motion-fast) var(--fn-ease);
}

[data-testid="stBaseButton-primary"]:hover {
    background-color: var(--fn-persimmon-deep) !important;
    border-color: var(--fn-persimmon-deep) !important;
}

[data-testid="stBaseButton-primary"]:active {
    transform: translateY(1px);
}

[data-testid="stBaseButton-tertiary"] {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    min-height: 1.5rem;
    padding: 0 !important;
    border: 0 !important;
    background: transparent !important;
    color: var(--fn-ink-muted) !important;
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-xs);
    letter-spacing: 0.08em;
    text-decoration: underline;
    text-decoration-color: var(--fn-rule);
    text-decoration-thickness: 1px;
    text-underline-offset: 0.25em;
    text-transform: uppercase;
}

/* A static inline SVG mask marks the replace action without adding a font icon;
   the button's own label remains the accessible name. */
[data-testid="stBaseButton-tertiary"]::before {
    content: "";
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
    background-color: currentColor;
    mask-image: url("$replace_icon");
    mask-position: center;
    mask-repeat: no-repeat;
    mask-size: contain;
}

[data-testid="stBaseButton-tertiary"]:hover,
[data-testid="stBaseButton-tertiary"]:focus-visible {
    color: var(--fn-ink) !important;
    text-decoration-color: currentColor;
}

[data-testid="stSpinner"] {
    display: flex;
    align-items: center;
    gap: var(--fn-space-2);
    color: var(--fn-ink-muted);
    font-family: var(--fn-font-mono);
    font-size: var(--fn-text-sm);
}

[data-testid="stSpinnerIcon"] {
    display: none;
}

[data-testid="stSpinner"]::before {
    content: "";
    width: 2.5rem;
    height: var(--fn-rule-weight-strong);
    background-image: linear-gradient(
        90deg,
        transparent 0%,
        var(--fn-persimmon-text) 50%,
        transparent 100%
    );
    background-repeat: no-repeat;
    background-position: center;
    background-size: 0% 100%;
    animation: fn-loading calc(var(--fn-motion-arrival) * 4) var(--fn-ease) infinite;
}

[data-testid="stMultiSelect"] input::placeholder,
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {
    color: var(--fn-ink-muted) !important;
    opacity: 1;
}

/* Streamlit 1.66 paints multiselect tags with the theme primary; the white-on-
   persimmon pair is checked for at least 4.5:1, so only shape and type change. */
[data-testid="stMultiSelectTagsContainer"] [data-tag] {
    border-radius: var(--fn-radius) !important;
    font-family: var(--fn-font-ui);
}

[data-testid="stMultiSelectTagsContainer"] [data-tag] span {
    font-weight: 500;
}

/* ---- motion ------------------------------------------------------------------------- */

@keyframes fn-rise-in {
    from {
        opacity: 0;
        transform: translateY(8px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

@keyframes fn-draw-rule {
    from {
        transform: scaleX(0);
    }
    to {
        transform: scaleX(1);
    }
}

@keyframes fn-ink-sweep {
    from {
        background-size: 0% 100%;
    }
    to {
        background-size: 100% 100%;
    }
}

@keyframes fn-fade-in {
    from {
        opacity: 0;
    }
    to {
        opacity: 1;
    }
}

@keyframes fn-tab-in {
    from {
        opacity: 0;
        transform: translateY(4px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

@keyframes fn-pulse {
    from {
        opacity: 0.35;
    }
    to {
        opacity: 0;
    }
}

@keyframes fn-loading {
    0% {
        background-size: 0% 100%;
    }
    45% {
        background-size: 100% 100%;
    }
    55% {
        background-size: 100% 100%;
    }
    100% {
        background-size: 0% 100%;
    }
}

/* Scroll-driven reveals: nothing but opacity/transform/background-size moves, and
   the unanimated default is the final, fully visible state. */
@supports (animation-timeline: view()) {
    @media (prefers-reduced-motion: no-preference) {
        .fn-page-heading,
        .fn-evidence-body,
        [data-testid="stExpander"] {
            animation-name: fn-rise-in;
            animation-duration: var(--fn-motion-standard);
            animation-timing-function: var(--fn-ease);
            animation-fill-mode: both;
            animation-timeline: view();
            animation-range: entry 0% entry 55%;
        }

        .fn-evidence-card::before {
            animation-name: fn-draw-rule;
            animation-duration: var(--fn-motion-standard);
            animation-timing-function: var(--fn-ease);
            animation-fill-mode: both;
            animation-timeline: view();
            animation-range: entry 0% entry 30%;
        }

        .fn-highlight {
            animation-name: fn-ink-sweep;
            animation-duration: var(--fn-motion-standard);
            animation-timing-function: var(--fn-ease);
            animation-fill-mode: both;
            animation-timeline: view();
            animation-range: entry 10% entry 55%;
        }
    }
}

/* A freshly produced grid or SQL card: one time-based arrival, never a scroll reveal. */
.fn-fresh {
    animation: fn-rise-in var(--fn-motion-arrival) var(--fn-ease) both;
}

.fn-fresh .fn-evidence-body,
.fn-fresh [data-testid="stExpander"] {
    animation: none;
}

.fn-fresh .fn-evidence-card::before {
    animation: fn-draw-rule var(--fn-motion-arrival) var(--fn-ease) both;
    animation-timeline: auto;
}

.fn-fresh .fn-highlight {
    animation: fn-ink-sweep calc(var(--fn-motion-arrival) * 0.75) var(--fn-ease) both;
    animation-timeline: auto;
}

.fn-fresh .fn-source-chip {
    animation: fn-fade-in var(--fn-motion-standard) var(--fn-ease)
        calc(var(--fn-motion-arrival) / 2) both;
}

/* The analysis result marker is a zero-size span; its block carries the arrival. */
[data-testid="stVerticalBlock"]:has(
    > [data-testid="stElementContainer"] .fn-result-marker.fn-fresh
) {
    position: relative;
    animation: fn-rise-in var(--fn-motion-arrival) var(--fn-ease) both;
}

[data-testid="stVerticalBlock"]:has(
    > [data-testid="stElementContainer"] .fn-result-marker.fn-fresh
)::before {
    content: "";
    position: absolute;
    top: 0;
    right: 0;
    left: 0;
    height: var(--fn-card-rule-weight);
    background: var(--fn-ink);
    transform-origin: left center;
    animation: fn-draw-rule var(--fn-motion-arrival) var(--fn-ease) both;
}

[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .fn-result-marker.fn-fresh)
    .fn-computed-from .fn-highlight {
    animation: fn-ink-sweep calc(var(--fn-motion-arrival) * 0.75) var(--fn-ease) both;
    animation-timeline: auto;
}

/* Hero intro: 40ms stagger, once per session because the class is not re-applied. */
.fn-intro .fn-hero-title {
    animation: fn-rise-in var(--fn-motion-arrival) var(--fn-ease) both;
}

.fn-intro .fn-hero-purpose {
    animation: fn-rise-in var(--fn-motion-arrival) var(--fn-ease)
        calc(var(--fn-motion-stagger) * 1) both;
}

.fn-intro .fn-hero-steps {
    animation: fn-rise-in var(--fn-motion-arrival) var(--fn-ease)
        calc(var(--fn-motion-stagger) * 2) both;
}

[data-testid="stTabPanel"]:has(.fn-intro) [data-testid="stBaseButton-primary"] {
    animation: fn-rise-in var(--fn-motion-arrival) var(--fn-ease)
        calc(var(--fn-motion-stagger) * 3) both;
}

/* Tab panels animate when they become displayed; reruns of the same panel do not
   restart the animation because the node and its display state are unchanged. */
[data-testid="stTabPanel"] {
    animation: fn-tab-in var(--fn-motion-tab) var(--fn-ease) both;
}

/* Card hover and keyboard focus: a 1px lift and a persimmon rule; focus also gets a
   visible ring. The movement is a transform, so nothing reflows. */
.fn-evidence-card {
    transition: transform var(--fn-motion-fast) var(--fn-ease);
}

.fn-evidence-card:hover,
.fn-evidence-card:focus-within {
    transform: translateY(-1px);
}

.fn-evidence-card:hover::before,
.fn-evidence-card:focus-within::before {
    height: calc(var(--fn-card-rule-weight) + 1px);
    background: var(--fn-persimmon-text);
}

.fn-evidence-card:has(:focus-visible) {
    outline: 2px solid var(--fn-persimmon-text);
    outline-offset: 3px;
}

.fn-computed-from.fn-pulse::after {
    animation: fn-pulse calc(var(--fn-motion-arrival) * 2) var(--fn-ease) both;
}

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation: none !important;
        transition: none !important;
        scroll-behavior: auto !important;
    }
}

/* ---- narrow screens ----------------------------------------------------------------- */

@media (max-width: 480px) {
    .fn-app-wordmark {
        font-size: var(--fn-text-xl);
    }

    .fn-app-subtitle {
        font-size: 0.7rem;
    }

    .fn-card-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--fn-space-3);
    }

    .fn-evidence-value {
        font-size: var(--fn-text-xl);
    }

    .fn-evidence-note {
        font-size: var(--fn-text-xs);
    }

    /* The tab already names the page; the repeated mono label adds nothing. */
    .fn-page-heading .fn-section-label {
        display: none;
    }

    .fn-hero-steps li {
        padding: 0 var(--fn-space-2);
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
        sage_tint=PALETTE.sage_tint,
        persimmon=PALETTE.persimmon,
        persimmon_text=PALETTE.persimmon_text,
        persimmon_deep=PALETTE.persimmon_deep,
        persimmon_tint=PALETTE.persimmon_tint,
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
        motion_fast=MOTION_FAST,
        motion_standard=MOTION_STANDARD,
        motion_arrival=MOTION_ARRIVAL,
        motion_tab=MOTION_TAB,
        motion_stagger=MOTION_STAGGER,
        easing=EASING,
        replace_icon=_REPLACE_ICON,
    )


def apply_theme() -> None:
    """Inject the one app-wide stylesheet and the delegated footnote listener."""
    st.markdown(f"<style>{build_css()}</style>", unsafe_allow_html=True)
    st.html(_INTERACTION_SCRIPT, unsafe_allow_javascript=True)


def fresh_class(key: str, token: object = None) -> str:
    """Return the fresh class only when *token* changed since the previous rerun."""
    stored = st.session_state.get(_FRESH_KEY)
    seen = dict(stored) if isinstance(stored, dict) else {}
    marker = repr(token)
    is_fresh = seen.get(key) != marker
    seen[key] = marker
    st.session_state[_FRESH_KEY] = seen
    return CLASSES["fresh"] if is_fresh else ""
