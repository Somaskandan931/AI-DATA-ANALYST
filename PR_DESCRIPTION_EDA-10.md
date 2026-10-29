# EDA-10: grounded dataset chat

**Branch:** `m1/chat`, stacked on `m1/report`
**Requirement ID:** EDA-10 (P3)
**Owner:** Somaskandan (M1) | **Reviewer:** Nishi or Prathin

## What this adds

| Area | Change |
| --- | --- |
| `chat/router.py` (new) | `route_question(question, profile)`: fixed rules map a question to a profile `Lookup`, one typed `Propose` step, or `Unsupported` |
| `chat/answer.py` (new) | `answer_question(question, profile, *, artifacts, data, proposer)` returns `ChatAnswer` (status, text, evidence, assumptions, warnings, artifact); `StepProposer` protocol for an optional model |
| `docs/ARCHITECTURE.md` | chat section |

## How answers stay grounded

- Text is built only through a writer that formats a number and records its `Evidence` (profile field or artifact result path) in one step. `ungrounded_numbers` then checks the finished text and fails closed: an answer with an untraceable number becomes an `unsupported` answer.
- Profile questions (counts, duplicates, missing values, per-column statistics, outlier counts) read the `DatasetProfile`. Anything else is one allow-listed step, validated with `validate_step`, reused if an artifact with the same parameters and cleaning log exists, otherwise run on the supplied frame or `CleanedView`.
- If nothing is computed and no data is given, or the data cannot support the operation, the answer says so. Router defaults (k=3, two components, the mean, all numeric columns) are listed as assumptions.
- The question is only matched against column names and a closed vocabulary; it is never executed or echoed. No model is called. A `StepProposer` may return a typed `AnalysisStep` for questions the rules miss; it gets the same validation and its text is never shown.
- `ChatError` for an artifact or view from another dataset, a frame with the wrong row count, or a question over 2,000 characters.

## Not in this PR (on purpose)

- Streamlit chat widget (`ui/`, separate PR), a provider adapter for `StepProposer`, row filters (filter contract pending), the P5 grounding benchmark.

## Results

- `pytest`: 777 passed, 1 skipped (729 before; 48 new in `tests/unit/test_chat.py`).
- `ruff check`, `ruff format --check`, `mypy` (strict): clean. Import-boundary test passes (`chat/` imports only M1 modules and `models`).
- Profile answers are compared with the profile values; computed answers are compared with the artifact's own numbers; every computed question in the tests has complete evidence; an answer with evidence recording disabled is refused.

## Review notes

- The vocabulary is English only and deliberately small. A question that does not fit is refused with the supported list rather than guessed at.
- Column and group names appear verbatim in the text; the UI renders them as text.
- No accuracy claim is made; routing accuracy needs the M1 benchmark questions.

## Checklist

- [x] Unit tests for new behaviour, including rejection and failure paths
- [x] `ruff check`, `ruff format --check`, `mypy`, `pytest` pass
- [x] No credentials, raw sensitive data or generated databases committed
- [x] Docs updated
- [ ] Review feedback addressed
