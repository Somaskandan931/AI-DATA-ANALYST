"""Deterministic ambiguity detection for natural-language SQL questions.

This module does not generate SQL or call an AI provider. It identifies a
small set of questions that need clarification before SQL generation.
"""

from dataclasses import dataclass

from ai_data_analyst.sql_agent.contracts import SchemaSnapshot


@dataclass(frozen=True, slots=True)
class AmbiguityResult:
    """Outcome of checking whether a question needs clarification."""

    needs_clarification: bool
    clarification_question: str | None = None


# Ranking words that can imply either a global or grouped result.
_RANKING_TERMS = (
    "highest",
    "lowest",
    "maximum",
    "minimum",
    "max",
    "min",
    "top",
    "bottom",
)

# Common words that indicate a ranking request.
_RANKING_CONTEXT = (
    "demand",
    "sales",
    "revenue",
    "profit",
    "price",
    "score",
    "value",
    "amount",
    "count",
    "total",
    "temperature",
)


def _normalise_question(question: str) -> str:
    """Normalize question text for simple deterministic matching."""
    return " ".join(question.casefold().strip().split())


def _is_ranking_question(question: str) -> bool:
    """Check whether the question appears to request ranked results."""
    words = set(question.replace("-", " ").split())

    has_ranking_term = any(term in words for term in _RANKING_TERMS)
    has_ranking_context = any(term in words for term in _RANKING_CONTEXT)

    return has_ranking_term and has_ranking_context


def _has_grouping_instruction(question: str) -> bool:
    """Avoid asking when the user has already specified the result scope."""
    grouping_phrases = (
        "for each",
        "per ",
        "by region",
        "by category",
        "group by",
        "grouped by",
        "in each",
        "overall",
        "across the entire dataset",
    )

    return any(phrase in question for phrase in grouping_phrases)


def _has_groupable_column(schema: SchemaSnapshot) -> bool:
    """Check whether an approved schema contains a likely grouping column."""
    grouping_names = {
        "region",
        "category",
        "type",
        "department",
        "country",
        "city",
        "state",
        "status",
        "product",
        "customer",
        "year",
        "month",
        "date",
    }

    return any(
        column.name.casefold() in grouping_names
        for table in schema.tables
        for column in table.columns
    )


def detect_ambiguity(
    question: str,
    schema: SchemaSnapshot,
) -> AmbiguityResult:
    """Detect supported ambiguity patterns before SQL generation.

    A ranking question may mean either a global ranking or a ranking
    within each available category. Ask the user when a likely grouping
    column exists and the question does not specify the grouping.
    """
    normalized = _normalise_question(question)

    if not normalized:
        return AmbiguityResult(
            needs_clarification=False,
        )

    if not schema.tables:
        return AmbiguityResult(
            needs_clarification=False,
        )

    if (
        _is_ranking_question(normalized)
        and _has_groupable_column(schema)
        and not _has_grouping_instruction(normalized)
    ):
        return AmbiguityResult(
            needs_clarification=True,
            clarification_question=(
                "Should I find the result across the entire dataset, "
                "or separately for each available category, such as region?"
            ),
        )

    return AmbiguityResult(
        needs_clarification=False,
    )
