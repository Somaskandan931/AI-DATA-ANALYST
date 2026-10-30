"""Grounded answer composition (EDA-10).

Every number in an answer's text is registered as :class:`Evidence` pointing at the profile
field or artifact result it was copied from. The text is built only through
:class:`_Writer`, which formats a value and records its evidence in one step, and a final
check (:func:`ungrounded_numbers`) fails closed if any number in the text lacks evidence.
No model-written text is included. If a question needs a result that has not been
computed, one allow-listed step is validated and run; otherwise the answer explains the
limitation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final, Literal, Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict

from ..analysis import (
    AnalysisArtifact,
    AnalysisStep,
    CleanedView,
    OperationInputError,
    PlanValidationError,
    execute_step,
    validate_step,
)
from ..models import ColumnProfile, DatasetProfile
from ..reporting._format import fmt_value, single_line
from .router import (
    SUPPORTED_QUESTIONS,
    Lookup,
    Propose,
    Stat,
    Unsupported,
    route_question,
)

CHAT_SCHEMA_VERSION: Final = "1.0"
MAX_QUESTION_LENGTH: Final = 2_000
_LISTED_GROUPS: Final = 10
_LISTED_CATEGORIES: Final = 5
_NUMBER: Final = re.compile(r"\d+(?:\.\d+)?")

AnswerStatus = Literal["profile", "artifact", "computed", "unsupported"]


class ChatError(ValueError):
    """The inputs do not fit together (foreign dataset, oversized question, wrong frame)."""


class Evidence(BaseModel):
    """Where one number in an answer came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["profile", "artifact"]
    reference: str
    value: str


class ChatAnswer(BaseModel):
    """``status``: ``profile`` (read from the profile), ``artifact`` (an existing artifact),
    ``computed`` (one new step was run; see ``artifact``) or ``unsupported``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = CHAT_SCHEMA_VERSION
    status: AnswerStatus
    text: str
    evidence: tuple[Evidence, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    artifact: AnalysisArtifact | None = None


class StepProposer(Protocol):
    """Optional model adapter for questions the rules do not cover.

    It may only return a typed :data:`AnalysisStep` (or ``None``). The step is validated
    against the profile exactly like any other; the adapter's text is never shown or run.
    """

    def propose(self, question: str, profile: DatasetProfile) -> AnalysisStep | None: ...


class _Writer:
    def __init__(self, source: Literal["profile", "artifact"]) -> None:
        self.source = source
        self.evidence: list[Evidence] = []
        self.labels: set[str] = set()

    def num(self, reference: str, value: object) -> str:
        text = fmt_value(value)
        self.evidence.append(Evidence(source=self.source, reference=reference, value=text))
        return text

    def label(self, value: object) -> str:
        """Text from the uploaded file (names, keys); it may contain digits."""
        text = single_line(str(value))
        self.labels.add(text)
        return text


def ungrounded_numbers(
    text: str, evidence: Sequence[Evidence], labels: Sequence[str] = ()
) -> list[str]:
    """Numbers in *text* (ignoring those inside *labels*) that no evidence value contains."""
    for label in sorted(labels, key=len, reverse=True):
        if label:  # only whole tokens, so "0" cannot eat part of "976.8"
            text = re.sub(rf"(?<![\w.]){re.escape(label)}(?![\w.])", " ", text)
    allowed = {token for item in evidence for token in _NUMBER.findall(item.value)}
    return [token for token in _NUMBER.findall(text) if token not in allowed]


def _col(profile: DatasetProfile, name: str) -> ColumnProfile:
    return next(c for c in profile.columns if c.name == name)


def _unsupported(reason: str) -> ChatAnswer:
    lines = " ".join(SUPPORTED_QUESTIONS)
    return ChatAnswer(status="unsupported", text=f"{reason} Supported questions: {lines}")


# ---- answers read from the profile ----------------------------------------------------------


def _from_profile(lookup: Lookup, profile: DatasetProfile) -> tuple[str, _Writer]:  # noqa: C901
    w = _Writer("profile")
    name = w.label(lookup.column) if lookup.column else ""
    match lookup.kind:
        case "row_count":
            text = f"The dataset has {w.num('profile.row_count', profile.row_count)} rows."
        case "column_count":
            n = w.num("profile.column_count", profile.column_count)
            text = f"The dataset has {n} columns."
        case "duplicates":
            d = w.num("profile.duplicate_row_count", profile.duplicate_row_count)
            text = f"{d} rows repeat an earlier row (the first occurrence is not counted)."
        case "missing_total":
            total = sum(c.missing_count for c in profile.columns)
            m = w.num("sum(profile.columns[*].missing_count)", total)
            cols = [c for c in profile.columns if c.missing_count]
            n = w.num("count(profile.columns with missing_count > 0)", len(cols))
            text = f"{m} cells are missing, across {n} columns."
        case "missing_column":
            m = w.num(f"profile.columns[{name}].missing_count", _col(profile, name).missing_count)
            r = w.num("profile.row_count", profile.row_count)
            text = f"{name} has {m} missing values out of {r} rows."
        case "columns":
            parts = [f"{w.label(c.name)} ({c.inferred_type})" for c in profile.columns]
            text = "Columns: " + ", ".join(parts) + "."
        case "column_type":
            text = f"{name} is inferred as {_col(profile, name).inferred_type}."
        case "outlier_overview":
            numeric = [c for c in profile.columns if c.outlier_count is not None]
            if not numeric:
                text = "There are no numeric columns, so no outliers are defined."
            else:
                parts = [
                    f"{w.label(c.name)}: "
                    + w.num(f"profile.columns[{c.name}].outlier_count", c.outlier_count)
                    for c in numeric
                ]
                text = "Outliers by the interquartile-range rule: " + "; ".join(parts) + "."
        case "outlier_column":
            o = w.num(f"profile.columns[{name}].outlier_count", _col(profile, name).outlier_count)
            text = f"{name} has {o} outliers by the interquartile-range rule."
        case "stat":
            text = _stat_text(profile, name, lookup.stat, w)
        case "column_describe":
            text = _describe(profile, name, w)
        case "overview":
            r = w.num("profile.row_count", profile.row_count)
            n = w.num("profile.column_count", profile.column_count)
            d = w.num("profile.duplicate_row_count", profile.duplicate_row_count)
            gaps = w.num(
                "sum(profile.columns[*].missing_count)",
                sum(col.missing_count for col in profile.columns),
            )
            text = f"{r} rows, {n} columns, {d} duplicate rows, {gaps} missing cells."
    return text, w


_STAT_FIELD: Final[dict[str, str]] = {
    "mean": "mean",
    "median": "median",
    "std": "std",
    "min": "min",
    "max": "max",
    "q1": "q1",
    "q3": "q3",
    "unique": "unique_count",
}
_STAT_NAME: Final[dict[str, str]] = {
    "mean": "mean",
    "median": "median",
    "std": "standard deviation",
    "min": "minimum",
    "max": "maximum",
    "q1": "first quartile",
    "q3": "third quartile",
    "unique": "number of distinct values",
}


def _stat_text(profile: DatasetProfile, name: str, stat: Stat | None, w: _Writer) -> str:
    if stat is None:
        return f"No statistic was named for {name}."
    column = _col(profile, name)
    field = _STAT_FIELD[stat]
    value = getattr(column, field)
    label = _STAT_NAME[stat]
    if value is None:
        return f"The {label} is not defined for {name} ({column.inferred_type} column)."
    shown = w.num(f"profile.columns[{name}].{field}", value)
    return f"The {label} of {name} is {shown}."


def _describe(profile: DatasetProfile, name: str, w: _Writer) -> str:
    c = _col(profile, name)
    base = f"{name} is a {c.inferred_type} column with "
    base += f"{w.num(f'profile.columns[{name}].missing_count', c.missing_count)} missing and "
    base += f"{w.num(f'profile.columns[{name}].unique_count', c.unique_count)} distinct values"
    if c.mean is None:
        return base + "."
    parts = [
        f"{label} {w.num(f'profile.columns[{name}].{field}', getattr(c, field))}"
        for label, field in (("mean", "mean"), ("median", "median"), ("min", "min"), ("max", "max"))
        if getattr(c, field) is not None
    ]
    return base + "; " + ", ".join(parts) + "."


# ---- answers composed from an artifact --------------------------------------------------------


def _obj(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ChatError("artifact result has an unexpected shape")
    return value


def _seq(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ChatError("artifact result has an unexpected shape")
    return value


def _from_artifact(artifact: AnalysisArtifact) -> tuple[str, _Writer]:  # noqa: C901
    w = _Writer("artifact")
    r = artifact.result
    lines: list[str] = []
    match artifact.operation:
        case "summary_stats":
            for name, raw in _obj(r["columns"]).items():
                s = _obj(raw)
                bits = ", ".join(
                    f"{key} {w.num(f'result.columns[{name}].{key}', s[key])}"
                    for key in ("count", "missing", "mean", "median", "std", "min", "max")
                )
                lines.append(f"{w.label(name)}: {bits}")
        case "distribution":
            lines.extend(_distribution_lines(r, w))
        case "correlation":
            names = [w.label(n) for n in _seq(r["columns"])]
            matrix, counts = _seq(r["matrix"]), _seq(r["pair_counts"])
            method = str(r["method"])
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    coefficient = w.num(f"result.matrix[{i}][{j}]", _seq(matrix[i])[j])
                    pairs = w.num(f"result.pair_counts[{i}][{j}]", _seq(counts[i])[j])
                    lines.append(
                        f"{names[i]} and {names[j]}: {method} correlation {coefficient} "
                        f"({pairs} paired values)"
                    )
        case "outlier_summary":
            for name, raw in _obj(r["columns"]).items():
                s = _obj(raw)
                base = f"result.columns[{name}]"
                count = w.num(f"{base}.outlier_count", s["outlier_count"])
                low = w.num(f"{base}.lower_bound", s["lower_bound"])
                high = w.num(f"{base}.upper_bound", s["upper_bound"])
                lines.append(f"{w.label(name)}: {count} outliers, normal range {low} to {high}")
        case "grouped_aggregation":
            lines.extend(_grouped_lines(r, w))
        case "clustering":
            lines.extend(_clustering_lines(r, w))
        case "pca":
            for index, raw in enumerate(_seq(r["components"])):
                c = _obj(raw)
                ratio = w.num(
                    f"result.components[{index}].explained_variance_ratio",
                    c["explained_variance_ratio"],
                )
                cumulative = w.num(
                    f"result.components[{index}].cumulative_ratio", c["cumulative_ratio"]
                )
                lines.append(
                    f"{w.label(str(c['component']))} explains {ratio} of the variance "
                    f"(cumulative {cumulative})"
                )
    used = w.num("provenance.rows_used", artifact.provenance.rows_used)
    return "\n".join(lines) + f"\nBased on {used} rows.", w


def _distribution_lines(r: dict[str, Any], w: _Writer) -> list[str]:
    name = w.label(r["column"])
    missing = w.num("result.missing", r["missing"])
    if r["kind"] == "histogram":
        edges, counts = _seq(r["bin_edges"]), _seq(r["counts"])
        top = max(range(len(counts)), key=lambda i: int(str(counts[i])))
        bins = w.num("result.counts (length)", len(counts))
        lo = w.num(f"result.bin_edges[{top}]", edges[top])
        hi = w.num(f"result.bin_edges[{top + 1}]", edges[top + 1])
        n = w.num(f"result.counts[{top}]", counts[top])
        first = w.num("result.bin_edges[0]", edges[0])
        last = w.num("result.bin_edges[-1]", edges[-1])
        return [
            f"{name}: values run from {first} to {last} in {bins} bins ({missing} missing).",
            f"The fullest bin spans {lo} to {hi} with {n} values.",
        ]
    values = _seq(r["values"])
    distinct = w.num("result.distinct", r["distinct"])
    out = [f"{name}: {distinct} distinct values ({missing} missing)."]
    for index, raw in enumerate(values[:_LISTED_CATEGORIES]):
        item = _obj(raw)
        count = w.num(f"result.values[{index}].count", item["count"])
        out.append(f"{w.label(str(item['value']))}: {count}")
    return out


def _grouped_lines(r: dict[str, Any], w: _Writer) -> list[str]:
    value = w.label(r["value_column"])
    aggs = [str(a) for a in _seq(r["aggregations"])]
    groups = _seq(r["groups"])
    total = w.num("result.total_groups", r["total_groups"])
    out = [f"{value} by {', '.join(w.label(g) for g in _seq(r['group_by']))} ({total} groups):"]
    for index, raw in enumerate(groups[:_LISTED_GROUPS]):
        g = _obj(raw)
        key = ", ".join(w.label(f"{v}") for v in _obj(g["keys"]).values())
        bits = ", ".join(f"{a} {w.num(f'result.groups[{index}].{a}', g[a])}" for a in aggs)
        out.append(f"{key}: {bits}")
    if len(groups) > _LISTED_GROUPS:
        shown = w.num("count(listed groups)", _LISTED_GROUPS)
        out.append(f"Only the first {shown} groups are listed.")
    if r.get("truncated"):
        out.append("The computation itself was limited to its first groups by key order.")
    return out


def _clustering_lines(r: dict[str, Any], w: _Writer) -> list[str]:
    k = w.num("result.k", r["k"])
    rows = w.num("result.rows_clustered", r["rows_clustered"])
    sil = r.get("silhouette")
    tail = f", silhouette {w.num('result.silhouette', sil)}" if sil is not None else ""
    out = [f"k-means with {k} clusters on {rows} complete rows{tail}."]
    for index, raw in enumerate(_seq(r["clusters"])):
        c = _obj(raw)
        centroid = ", ".join(
            f"{w.label(col)} {w.num(f'result.clusters[{index}].centroid.{col}', v)}"
            for col, v in _obj(c["centroid"]).items()
        )
        size = w.num(f"result.clusters[{index}].size", c["size"])
        ident = w.num(f"result.clusters[{index}].cluster", c["cluster"])
        out.append(f"Cluster {ident}: {size} rows; centroid {centroid}")
    return out


# ---- entry point ------------------------------------------------------------------------------


def _checked_artifacts(profile: DatasetProfile, artifacts: Sequence[AnalysisArtifact]) -> None:
    for artifact in artifacts:
        if artifact.provenance.dataset_fingerprint != profile.dataset_fingerprint:
            raise ChatError("an artifact was computed on a different dataset (fingerprint)")


def _finish(
    status: AnswerStatus,
    text: str,
    writer: _Writer,
    assumptions: tuple[str, ...] = (),
    artifact: AnalysisArtifact | None = None,
    notes: tuple[str, ...] = (),
) -> ChatAnswer:
    bad = ungrounded_numbers(text, writer.evidence, sorted(writer.labels))
    if bad:  # fail closed: never show a number we cannot trace
        return _unsupported("The answer could not be grounded in a computed result.")
    warnings = list(artifact.warnings) if artifact else []
    warnings.extend(notes)
    if artifact and artifact.provenance.cleaning:
        warnings.append("Computed on cleaned data: " + "; ".join(artifact.provenance.cleaning))
    return ChatAnswer(
        status=status,
        text=text,
        evidence=tuple(writer.evidence),
        assumptions=assumptions,
        warnings=tuple(warnings),
        artifact=artifact,
    )


def answer_question(
    question: str,
    profile: DatasetProfile,
    *,
    artifacts: Sequence[AnalysisArtifact] = (),
    data: pd.DataFrame | CleanedView | None = None,
    proposer: StepProposer | None = None,
) -> ChatAnswer:
    """Answer *question* from the profile, existing *artifacts*, or one new allow-listed step.

    *data* is the typed frame (or cleaned view) a new step may run on; without it, nothing
    new is computed. Raises :class:`ChatError` for a foreign artifact or view, a frame that
    does not match the profile, or an over-long question.
    """
    if len(question) > MAX_QUESTION_LENGTH:
        raise ChatError(f"question is longer than {MAX_QUESTION_LENGTH} characters")
    _checked_artifacts(profile, artifacts)
    frame: pd.DataFrame | None = None
    cleaning: tuple[str, ...] = ()
    if isinstance(data, CleanedView):
        if data.dataset_fingerprint != profile.dataset_fingerprint:
            raise ChatError("cleaned view belongs to a different dataset (fingerprint)")
        frame, cleaning = data.frame, data.log
    elif data is not None:
        if len(data) != profile.row_count:
            raise ChatError("frame does not match the profile (row count differs)")
        frame = data

    route = route_question(question, profile)
    assumptions: tuple[str, ...] = ()
    if isinstance(route, Unsupported) and proposer is not None:
        proposed = proposer.propose(question, profile)
        if proposed is not None:
            route = Propose(proposed, ("The step was proposed by a model and validated.",))
    if isinstance(route, Unsupported):
        return _unsupported(route.reason)
    if isinstance(route, Lookup):
        text, writer = _from_profile(route, profile)
        notes = (
            ("Describes the file as uploaded, not the cleaned data: " + "; ".join(cleaning),)
            if cleaning
            else ()
        )
        return _finish("profile", text, writer, notes=notes)

    step, assumptions = route.step, route.assumptions
    try:
        validate_step(step, profile)
    except PlanValidationError as error:
        return _unsupported(f"That analysis does not fit this dataset: {error}.")
    wanted = step.model_dump(mode="json")
    for artifact in artifacts:
        if artifact.parameters == wanted and artifact.provenance.cleaning == cleaning:
            text, writer = _from_artifact(artifact)
            return _finish("artifact", text, writer, assumptions, artifact)
    if frame is None:
        return _unsupported(
            "That result has not been computed and no data is loaded to compute it."
        )
    try:
        artifact = execute_step(step, frame, profile, cleaning)
    except OperationInputError as error:
        return _unsupported(f"The data cannot support that analysis: {error}.")
    text, writer = _from_artifact(artifact)
    return _finish("computed", text, writer, assumptions, artifact)
