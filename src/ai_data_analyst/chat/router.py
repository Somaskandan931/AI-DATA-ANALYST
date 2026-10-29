"""Question routing (EDA-10).

Turns a question into one of three things, using fixed rules only (no model, no code
generation): a lookup in the :class:`~ai_data_analyst.models.DatasetProfile`, one typed
allow-listed analysis step, or an explanation that the question is not supported. The
question text is only ever matched against column names and a closed vocabulary; it is never
executed, evaluated or passed on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

from ..analysis import (
    AnalysisStep,
    ClusteringParams,
    CorrelationParams,
    DistributionParams,
    GroupedAggregationParams,
    PcaParams,
    SummaryStatsParams,
)
from ..models import ColumnProfile, DatasetProfile

LookupKind = Literal[
    "overview",
    "row_count",
    "column_count",
    "duplicates",
    "missing_total",
    "missing_column",
    "columns",
    "column_type",
    "column_describe",
    "outlier_overview",
    "outlier_column",
    "stat",
]
Stat = Literal["mean", "median", "std", "min", "max", "q1", "q3", "unique"]

SUPPORTED_QUESTIONS: Final = (
    "How many rows and columns are there? Are there duplicate rows?",
    "How many values are missing (overall or in a column)?",
    "What is the mean, median, minimum, maximum or standard deviation of a column?",
    "How many outliers does a column have?",
    "What is the distribution of a column?",
    "What is the average (or sum, count, min, max) of a numeric column by a category column?",
    "How are two numeric columns correlated?",
    "Cluster the data into k groups using numeric columns; run PCA on numeric columns.",
)

_NUMERIC: Final = frozenset({"integer", "float"})
_GROUPABLE: Final = frozenset({"integer", "boolean", "date", "string"})
_MAX_NAMED_COLUMNS: Final = 20

_STAT_WORDS: Final[tuple[tuple[str, Stat], ...]] = (
    (r"standard deviation|std|stdev|deviation", "std"),
    (r"median", "median"),
    (r"mean|average|avg", "mean"),
    (r"minimum|lowest|smallest|earliest|\bmin\b", "min"),
    (r"maximum|highest|largest|biggest|latest|\bmax\b", "max"),
    (r"first quartile|\bq1\b|25th percentile", "q1"),
    (r"third quartile|\bq3\b|75th percentile", "q3"),
    (r"unique|distinct", "unique"),
)
_AGG_WORDS: Final = (
    (r"standard deviation|std|stdev|deviation", "std"),
    (r"median", "median"),
    (r"mean|average|avg", "mean"),
    (r"sum|total", "sum"),
    (r"minimum|lowest|smallest|\bmin\b", "min"),
    (r"maximum|highest|largest|biggest|\bmax\b", "max"),
    (r"count|number of|how many", "count"),
)
_FILTER_INTENT: Final = re.compile(
    r"[<>=]|\bwhere\b|\bwhich rows\b|\b(?:drop|remove|delete|filter|exclude|keep)\b"
    r"|\b(?:rows|records)\s+(?:have|has|with|that|whose)\b"
    r"|\bshow (?:me )?(?:the )?(?:rows|records)\b"
)
_UNSUPPORTED_STAT: Final = re.compile(
    r"percentile|quantile|\bmode\b|variance|skew|kurtosis|\brange\b|\bcv\b"
)
_GROUP_WORD: Final = re.compile(r"\b(?:by|per|for each|grouped by|broken down by|across)\b")


@dataclass(frozen=True)
class Lookup:
    """Answer from the profile; nothing needs computing."""

    kind: LookupKind
    column: str | None = None
    stat: Stat | None = None


@dataclass(frozen=True)
class Propose:
    """Answer needs one allow-listed analysis step (reused if already computed)."""

    step: AnalysisStep
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Unsupported:
    reason: str


Route = Lookup | Propose | Unsupported


def _mentions(question: str, profile: DatasetProfile) -> list[tuple[int, str]]:
    """Columns named in *question* as ``(position, name)``, in order of appearance."""
    text = question.lower()
    taken = [False] * len(text)
    found: list[tuple[int, str]] = []
    for column in sorted(profile.columns, key=lambda c: -len(c.name)):
        lowered = column.name.lower()
        variants = {lowered, re.sub(r"[_\-]+", " ", lowered).strip()}
        for variant in sorted(variants - {""}, key=len, reverse=True):
            pattern = rf"(?<![a-z0-9_]){re.escape(variant)}(?![a-z0-9_])"
            for match in re.finditer(pattern, text):
                span = range(match.start(), match.end())
                if any(taken[i] for i in span):
                    continue
                for i in span:
                    taken[i] = True
                found.append((match.start(), column.name))
                break
            else:
                continue
            break
    found.sort()
    unique: list[tuple[int, str]] = []
    for position, name in found:
        if all(name != existing for _, existing in unique):
            unique.append((position, name))
    return unique[:_MAX_NAMED_COLUMNS]


def _kind(profile: DatasetProfile, name: str) -> str:
    return next(c.inferred_type for c in profile.columns if c.name == name)


def _column(profile: DatasetProfile, name: str) -> ColumnProfile:
    return next(c for c in profile.columns if c.name == name)


def _first(text: str, table: tuple[tuple[str, str], ...]) -> str | None:
    best: tuple[int, str] | None = None
    for pattern, value in table:
        match = re.search(pattern, text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), value)
    return best[1] if best else None


def _int_after(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _numeric_columns(profile: DatasetProfile) -> list[str]:
    return [c.name for c in profile.columns if c.inferred_type in _NUMERIC]


def _multi_numeric(
    profile: DatasetProfile, named: list[str], low: int, high: int, what: str
) -> tuple[tuple[str, ...], tuple[str, ...]] | Unsupported:
    """Numeric columns for a multi-column operation: the named ones, else all of them."""
    numeric_named = [n for n in named if _kind(profile, n) in _NUMERIC]
    if len(numeric_named) != len(named):
        return Unsupported(f"{what} needs numeric columns; some named columns are not numeric.")
    if numeric_named:
        chosen: list[str] = numeric_named
        note: tuple[str, ...] = ()
    else:
        chosen = _numeric_columns(profile)
        note = (f"No columns were named, so all {len(chosen)} numeric columns were used.",)
    if len(chosen) < low:
        return Unsupported(f"{what} needs at least {low} numeric columns.")
    if len(chosen) > high:
        return Unsupported(f"{what} accepts at most {high} columns; name the ones to use.")
    return tuple(chosen), note


def route_question(question: str, profile: DatasetProfile) -> Route:  # noqa: C901
    """Choose how to answer *question*. Never raises for ordinary text."""
    text = " ".join(question.lower().split())
    if not text:
        return Unsupported("The question is empty.")
    mentions = _mentions(text, profile)
    named = [name for _, name in mentions]
    numeric = [n for n in named if _kind(profile, n) in _NUMERIC]

    if re.search(r"correlat|relationship between|related to", text):
        if len(numeric) < 2 or len(numeric) != len(named):
            return Unsupported("A correlation needs two or more numeric columns; name them.")
        method = "spearman" if "spearman" in text else "pearson"
        return Propose(CorrelationParams(columns=tuple(named), method=method))

    if re.search(r"cluster|segment", text):
        chosen = _multi_numeric(profile, named, 2, 10, "Clustering")
        if isinstance(chosen, Unsupported):
            return chosen
        k = _int_after(
            text, (r"\bk\s*=\s*(\d+)", r"(\d+)\s*(?:clusters|groups|segments)", r"into\s+(\d+)")
        )
        assumptions = chosen[1]
        if k is None:
            k = 3
            assumptions = (*assumptions, "No cluster count was given, so k=3 was used.")
        if not 2 <= k <= 10:
            return Unsupported("The number of clusters must be between 2 and 10.")
        return Propose(ClusteringParams(columns=chosen[0], k=k), assumptions)

    if re.search(r"\bpca\b|principal component", text):
        chosen = _multi_numeric(profile, named, 2, 20, "PCA")
        if isinstance(chosen, Unsupported):
            return chosen
        components = _int_after(text, (r"(\d+)\s*(?:principal )?components?",))
        assumptions = chosen[1]
        if components is None:
            components = 2
            assumptions = (*assumptions, "No component count was given, so 2 was used.")
        if not 1 <= components <= min(10, len(chosen[0])):
            return Unsupported(
                "The number of components must be 1 to 10, and no more than the number of columns."
            )
        return Propose(PcaParams(columns=chosen[0], n_components=components), assumptions)

    if _FILTER_INTENT.search(text):
        return Unsupported(
            "Row filtering is not available, so questions about a subset of rows cannot be "
            "answered."
        )

    group_match = _GROUP_WORD.search(text)
    if group_match and len(named) >= 2:
        after = [n for p, n in mentions if p >= group_match.end()]
        before = [n for p, n in mentions if p < group_match.start()]
        values = [n for n in before if _kind(profile, n) in _NUMERIC] or [
            n for n in before if n not in after
        ]
        if after and values:
            groups = [n for n in after if _kind(profile, n) in _GROUPABLE and n != values[0]]
            aggregation = _first(text[: group_match.start()], _AGG_WORDS)
            group_notes: tuple[str, ...] = ()
            if aggregation is None:
                aggregation = "mean"
                group_notes = ("No aggregation was named, so the mean was used.",)
            if not groups or len(groups) > 3:
                return Unsupported(
                    "Group by one to three category, boolean, integer or date columns."
                )
            if _kind(profile, values[0]) not in _NUMERIC and aggregation != "count":
                return Unsupported(f"{values[0]} is not numeric; only a count can be grouped.")
            return Propose(
                GroupedAggregationParams(
                    group_by=tuple(groups),
                    value_column=values[0],
                    aggregations=(aggregation,),
                ),
                group_notes,
            )

    if re.search(r"outlier|anomal", text):
        if len(named) == 1 and numeric:
            return Lookup("outlier_column", named[0])
        if not named:
            return Lookup("outlier_overview")
        return Unsupported("Outliers can be counted for numeric columns; name one numeric column.")

    if re.search(r"distribution|histogram|frequenc|breakdown|most common|least common", text):
        if len(named) != 1:
            return Unsupported("A distribution is for one column; name exactly one.")
        bins = _int_after(text, (r"(\d+)\s*bins",))
        if bins is not None and not 2 <= bins <= 100:
            return Unsupported("The number of bins must be between 2 and 100.")
        if bins is None:
            return Propose(DistributionParams(column=named[0]))
        return Propose(DistributionParams(column=named[0], bins=bins))

    if re.search(r"\bmissing\b|\bnull\b|\bblank\b|\bempty\b|\bnan\b|\bna\b", text):
        if len(named) == 1:
            return Lookup("missing_column", named[0])
        return (
            Lookup("missing_total")
            if not named
            else Unsupported("Name one column, or none for the whole dataset.")
        )

    if "duplicate" in text:
        return Lookup("duplicates")
    if re.search(r"how many columns|number of columns|column count", text):
        return Lookup("column_count")
    if re.search(
        r"how many (?:rows|records|observations)|number of (?:rows|records)|row count", text
    ):
        return Lookup("row_count")

    stat = _first(text, _STAT_WORDS)
    if stat is None and _UNSUPPORTED_STAT.search(text):
        return Unsupported(
            "That statistic is not computed. Available: mean, median, minimum, maximum, "
            "standard deviation, quartiles and distinct count."
        )
    if stat is not None and len(named) == 1:
        return Lookup("stat", named[0], stat)  # type: ignore[arg-type]
    if re.search(r"data ?type|what type|type of", text) and len(named) == 1:
        return Lookup("column_type", named[0])

    if re.search(r"summar|describe|statistics|stats|overview|profile", text):
        if numeric and len(numeric) == len(named):
            return Propose(SummaryStatsParams(columns=tuple(named)))
        if not named:
            return Lookup("overview")
    if re.search(r"which columns|list (?:the )?columns|what columns|column names|schema", text):
        return Lookup("columns")
    if len(named) == 1:
        return Lookup("column_describe", named[0])
    if stat is not None and len(named) > 1 and all(n in numeric for n in named):
        return Propose(SummaryStatsParams(columns=tuple(named)))

    return Unsupported("I can only answer questions that map to a computed result.")
