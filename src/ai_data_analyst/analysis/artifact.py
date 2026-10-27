"""``AnalysisArtifact``: one executed operation with its inputs, result and provenance.

Every number a chart, report or chat answer shows must trace back to an artifact (PRD
acceptance criterion 5). Results are plain JSON values with no NaN or infinity; undefined
statistics are ``None``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .plan import ANALYSIS_SCHEMA_VERSION, OperationName


class Provenance(BaseModel):
    """What produced an artifact, for reproducibility (APP-04)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows_in_dataset: int = Field(ge=0)
    rows_used: int = Field(ge=0, description="Rows that contributed to the result")
    library_versions: dict[str, str]


class AnalysisArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    operation: OperationName
    input_columns: tuple[str, ...]
    parameters: dict[str, JsonValue]
    result: dict[str, JsonValue]
    warnings: tuple[str, ...] = ()
    provenance: Provenance
