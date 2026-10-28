"""EDA-09: the report is built only from computed artifacts, fails closed, and escapes the data."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_data_analyst.analysis import (
    AnalysisArtifact,
    AnalysisPlan,
    ClusteringParams,
    CorrelationParams,
    DistributionParams,
    DropDuplicatesStep,
    GroupedAggregationParams,
    ImputeStep,
    OutlierSummaryParams,
    PcaParams,
    SummaryStatsParams,
    cleaned_view,
    execute_plan,
    execute_plan_on_view,
    typed_frame,
)
from ai_data_analyst.analysis.cleaning import CleaningPlan
from ai_data_analyst.ingestion import IngestedCSV, load_csv, load_csv_path
from ai_data_analyst.models import DatasetProfile
from ai_data_analyst.profiling import profile_ingested
from ai_data_analyst.reporting import (
    Report,
    ReportError,
    ReportTable,
    build_report,
    chart_svg,
    render_html,
    render_markdown,
)
from ai_data_analyst.reporting._format import (
    escape_html,
    escape_markdown,
    fmt_value,
    single_line,
)
from ai_data_analyst.visualization import ChartSpec, charts_for_artifacts

_NUMERIC = ("demand_mwh", "temperature_c")


def _plan() -> AnalysisPlan:
    return AnalysisPlan(
        steps=(
            SummaryStatsParams(columns=_NUMERIC),
            DistributionParams(column="demand_mwh", bins=8),
            DistributionParams(column="region"),
            GroupedAggregationParams(
                group_by=("region",), value_column="demand_mwh", aggregations=("mean", "count")
            ),
            CorrelationParams(columns=_NUMERIC),
            OutlierSummaryParams(columns=_NUMERIC),
            ClusteringParams(columns=_NUMERIC, k=3),
            PcaParams(columns=_NUMERIC),
        )
    )


@pytest.fixture(scope="module")
def ingested(sample_csv_path: Path) -> IngestedCSV:
    return load_csv_path(sample_csv_path)


@pytest.fixture(scope="module")
def profile(ingested: IngestedCSV) -> DatasetProfile:
    return profile_ingested(ingested)


@pytest.fixture(scope="module")
def artifacts(ingested: IngestedCSV, profile: DatasetProfile) -> tuple[AnalysisArtifact, ...]:
    return execute_plan(_plan(), typed_frame(ingested, profile), profile)


@pytest.fixture(scope="module")
def cleaned_artifacts(
    ingested: IngestedCSV, profile: DatasetProfile
) -> tuple[AnalysisArtifact, ...]:
    cleaning = CleaningPlan(
        steps=(DropDuplicatesStep(), ImputeStep(column="demand_mwh", strategy="median"))
    )
    return execute_plan_on_view(_plan(), cleaned_view(ingested, profile, cleaning), profile)


@pytest.fixture(scope="module")
def report(profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]) -> Report:
    return build_report(profile, artifacts, source_name="electricity_demand.csv")


def _table(report: Report, step: int, caption_start: str) -> ReportTable:
    (match,) = (t for t in report.results[step].tables if t.caption.startswith(caption_start))
    return match


def _retarget(artifact: AnalysisArtifact, **provenance: Any) -> AnalysisArtifact:
    return artifact.model_copy(
        update={"provenance": artifact.provenance.model_copy(update=provenance)}
    )


# --- the overview comes from the profile, checked against independent expected values -------


def test_overview_matches_the_independently_computed_profile(
    report: Report, expected_profile: dict[str, Any]
):
    facts = dict(report.overview_facts)
    assert facts == {
        "Rows": str(expected_profile["row_count"]),
        "Columns": str(expected_profile["column_count"]),
        "Duplicate rows": str(expected_profile["duplicate_row_count"]),
    }
    assert report.provenance.dataset_fingerprint == expected_profile["dataset_fingerprint"]
    headers = report.column_table.headers
    by_name = {row[0]: dict(zip(headers, row, strict=True)) for row in report.column_table.rows}
    for column in expected_profile["columns"]:
        row = by_name[column["name"]]
        assert row["Type"] == column["inferred_type"]
        assert row["Missing"] == str(column["missing_count"])
        assert row["Distinct"] == str(column["unique_count"])
        assert row["Min"] == fmt_value(column["min"])
        assert row["Max"] == fmt_value(column["max"])
        assert row["Mean"] == fmt_value(column["mean"])
        assert row["Outliers (IQR)"] == fmt_value(column["outlier_count"])
    assert by_name["demand_mwh"]["Missing (%)"] == "0.8"  # 4 of 485 rows


def test_summary_stats_table_repeats_the_profile_mean_of_the_same_column(
    report: Report, expected_profile: dict[str, Any]
):
    table = _table(report, 0, "Statistics")
    row = dict(zip(table.headers, next(r for r in table.rows if r[0] == "demand_mwh"), strict=True))
    expected = next(c for c in expected_profile["columns"] if c["name"] == "demand_mwh")
    assert row["Mean"] == fmt_value(expected["mean"])
    assert row["Median"] == fmt_value(expected["median"])
    assert row["Std"] == fmt_value(expected["std"])
    assert row["Count"] == str(485 - expected["missing_count"])


# --- every number in the results is the artifact's number ----------------------------------------


def test_one_method_and_one_result_per_artifact_in_plan_order(
    report: Report, artifacts: tuple[AnalysisArtifact, ...]
):
    assert [m.operation for m in report.methods] == [a.operation for a in artifacts]
    assert [r.operation for r in report.results] == [a.operation for a in artifacts]
    assert [m.step for m in report.methods] == list(range(len(artifacts)))
    for method, artifact in zip(report.methods, artifacts, strict=True):
        assert method.input_columns == artifact.input_columns
        assert method.rows_used == artifact.provenance.rows_used
        assert method.rows_in_dataset == artifact.provenance.rows_in_dataset
        assert method.description
        assert "operation" not in dict(method.parameters)


def test_grouped_aggregation_table_equals_the_artifact(
    report: Report, artifacts: tuple[AnalysisArtifact, ...]
):
    table = _table(report, 3, "Aggregations")
    groups: Any = artifacts[3].result["groups"]
    assert table.headers == ("region", "mean of demand_mwh", "count of demand_mwh")
    assert table.rows == tuple(
        (g["keys"]["region"], fmt_value(g["mean"]), fmt_value(g["count"])) for g in groups
    )


def test_correlation_matrix_is_symmetric_with_a_unit_diagonal(
    report: Report, ingested: IngestedCSV
):
    table = _table(report, 4, "Pearson")
    cells = [[float(c) for c in row[1:]] for row in table.rows]
    assert cells[0][0] == cells[1][1] == 1.0
    assert cells[0][1] == cells[1][0]
    # Pair counts, recomputed from the raw (untyped) cells: where a value exists, not its value.
    present = ingested.frame[list(_NUMERIC)].notna()
    both = int((present.demand_mwh & present.temperature_c).sum())
    counts = _table(report, 4, "Rows where both")
    assert counts.rows[0][1:] == (str(int(present.demand_mwh.sum())), str(both))
    assert counts.rows[1][1:] == (str(both), str(int(present.temperature_c.sum())))


def test_histogram_bins_account_for_every_non_missing_value(report: Report):
    table = _table(report, 1, "Equal-width")
    assert len(table.rows) == 8
    assert sum(int(row[1]) for row in table.rows) == 481  # 485 rows, 4 missing


def test_clustering_table_is_consistent_with_its_own_facts(report: Report):
    facts = dict(report.results[6].facts)
    table = _table(report, 6, "Clusters")
    sizes = [int(row[1]) for row in table.rows]
    assert sum(sizes) == int(facts["Rows clustered"]) == 469
    assert sizes == sorted(sizes, reverse=True)  # largest first
    assert facts["Clusters (k)"] == "3" and facts["Random seed"] == "0"
    assert table.headers[3:] == ("Mean of demand_mwh", "Mean of temperature_c")


def test_pca_variance_ratios_sum_to_one_and_cumulate(report: Report):
    table = _table(report, 7, "Variance")
    ratios = [float(row[2]) for row in table.rows]
    assert sum(ratios) == pytest.approx(1.0, abs=1e-5)
    assert float(table.rows[-1][3]) == pytest.approx(sum(ratios), abs=1e-5)
    loadings = _table(report, 7, "Loadings")
    assert loadings.headers == ("Column", "PC1", "PC2")


def test_undefined_values_print_as_n_a_never_as_a_number():
    assert fmt_value(None) == "n/a"
    assert fmt_value(float("nan")) == "n/a" and fmt_value(float("inf")) == "n/a"


def test_charts_are_the_specs_of_the_artifacts_and_linked_from_their_step(
    report: Report, artifacts: tuple[AnalysisArtifact, ...]
):
    assert report.charts == charts_for_artifacts(artifacts)
    assert len(report.charts) == 8
    for result in report.results:
        assert all(report.charts[i].source_step == result.step for i in result.chart_indices)
    linked = sorted(i for r in report.results for i in r.chart_indices)
    assert linked == list(range(8))


# --- warnings and limitations --------------------------------------------------------------------


def test_dataset_warnings_come_first_and_come_from_the_profile(report: Report):
    scopes = [w.scope for w in report.warnings]
    assert scopes == sorted(scopes, key=lambda s: s != "Dataset")  # all "Dataset" first
    dataset = [w.message for w in report.warnings if w.scope == "Dataset"]
    assert "5 duplicate rows (1.0% of rows) are present" in dataset
    assert any("'demand_mwh' has 4 missing values (0.8%)" in m for m in dataset)
    assert any("'temperature_c' has 12 missing values (2.5%)" in m for m in dataset)
    assert any("'demand_mwh' has 3 candidate outliers" in m for m in dataset)


def test_artifact_warnings_are_kept_and_say_which_step_they_came_from(
    report: Report, artifacts: tuple[AnalysisArtifact, ...]
):
    step_warnings = [(w.scope, w.message) for w in report.warnings if w.scope != "Dataset"]
    expected = [
        (f"Step {i + 1} ({report.results[i].title.split(': ')[1]})", text)
        for i, a in enumerate(artifacts)
        for text in a.warnings
    ]
    assert step_warnings == expected
    assert any("missing values" in message for _, message in step_warnings)


def test_a_wide_dataset_caps_its_per_column_warnings():
    columns = [f"c{i}" for i in range(30)]
    rows = ["id," + ",".join(columns)] + [
        f"{n}," + ",".join("" if n == 0 else "1" for _ in columns) for n in range(5)
    ]
    ingested = load_csv("\n".join(rows).encode(), "wide.csv")
    profile = profile_ingested(ingested)
    messages = [w.message for w in build_report(profile, []).warnings if "missing" in w.message]
    assert len(messages) == 21
    assert messages[-1] == "10 more columns have missing values"


def test_report_without_analyses_says_so(profile: DatasetProfile):
    report = build_report(profile, [])
    assert report.methods == () and report.results == () and report.charts == ()
    assert any(w.message == "No analyses were run" for w in report.warnings)
    assert "No analyses were run." in render_html(report)
    assert "No analyses were run." in render_markdown(report)


def test_limitations_follow_the_operations_that_were_run(
    profile: DatasetProfile, ingested: IngestedCSV, artifacts: tuple[AnalysisArtifact, ...]
):
    everything = " ".join(build_report(profile, artifacts).limitations)
    for phrase in ("k-means", "PCA", "Correlation measures", "candidates to look at"):
        assert phrase in everything
    assert "No cleaning was applied" in everything

    plan = AnalysisPlan(steps=(SummaryStatsParams(columns=_NUMERIC),))
    only_stats = execute_plan(plan, typed_frame(ingested, profile), profile)
    narrow = " ".join(build_report(profile, only_stats).limitations)
    assert "k-means" not in narrow and "PCA" not in narrow and "Correlation" not in narrow
    assert "no model-written text" in narrow


def test_cleaned_results_carry_their_cleaning_log_and_a_limitation(
    profile: DatasetProfile, cleaned_artifacts: tuple[AnalysisArtifact, ...]
):
    report = build_report(profile, cleaned_artifacts)
    log = cleaned_artifacts[0].provenance.cleaning
    assert len(log) == 2
    assert all(method.cleaning == log for method in report.methods)
    assert any("computed on a cleaned copy" in note for note in report.limitations)
    assert not any("No cleaning was applied" in note for note in report.limitations)
    assert report.methods[0].rows_in_dataset == 480  # 485 rows minus 5 duplicates
    for text in (render_html(report), render_markdown(report)):
        assert "Removed 5 duplicate rows" in text
        assert "Cleaning applied before this step" in text


# --- determinism, serialisation ------------------------------------------------------------------


def test_same_inputs_give_the_same_report_and_the_same_files(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    first, second = build_report(profile, artifacts), build_report(profile, artifacts)
    assert first == second
    assert render_html(first) == render_html(second)
    assert render_markdown(first) == render_markdown(second)
    assert first.provenance.generated_at is None
    assert "Generated:" not in render_html(first)


def test_generated_at_and_source_name_are_printed_only_when_given(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    report = build_report(
        profile, artifacts, source_name="demand.csv", generated_at="2026-10-28T10:00:00Z"
    )
    for text in (render_html(report), render_markdown(report)):
        assert "demand.csv" in text and "2026-10-28T10:00:00Z" in text


def test_report_round_trips_through_json(report: Report):
    assert Report.model_validate_json(report.model_dump_json()) == report


def test_report_records_the_versions_it_was_built_with(report: Report):
    prov = report.provenance
    assert prov.report_schema_version == report.schema_version == "1.0"
    assert set(prov.library_versions) == {"pandas", "numpy", "scipy", "scikit-learn"}
    assert "scikit-learn" in render_html(report) and "scikit-learn" in render_markdown(report)


def test_table_rejects_ragged_rows():
    with pytest.raises(ValidationError, match="one cell per header"):
        ReportTable(caption="x", headers=("a", "b"), rows=(("1",),))


# --- fail closed ---------------------------------------------------------------------------------


def test_artifact_from_another_dataset_is_rejected(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    foreign = _retarget(artifacts[2], dataset_fingerprint="0" * 64)
    with pytest.raises(ReportError, match=r"step 1 \(distribution\).*different dataset"):
        build_report(profile, [artifacts[0], foreign])


def test_artifact_that_used_more_rows_than_the_dataset_has_is_rejected(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    inflated = _retarget(artifacts[0], rows_in_dataset=profile.row_count + 1)
    with pytest.raises(ReportError, match="more rows than the dataset has"):
        build_report(profile, [inflated])


def test_too_many_steps_are_rejected(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    with pytest.raises(ReportError, match="at most 20"):
        build_report(profile, [artifacts[0]] * 21)


def test_a_chart_that_does_not_trace_to_its_artifact_is_rejected(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    good = charts_for_artifacts(artifacts)
    edited = good[0].model_copy(update={"values": tuple(v * 2 for v in good[0].values or ())})
    with pytest.raises(ReportError, match="chart 1 does not trace"):
        build_report(profile, artifacts, [edited])
    relabelled = good[1].model_copy(update={"title": "Something else"})
    with pytest.raises(ReportError, match="chart 2 does not trace"):
        build_report(profile, artifacts, [good[0], relabelled])
    orphan = good[0].model_copy(update={"source_step": 99})
    with pytest.raises(ReportError, match="does not exist"):
        build_report(profile, artifacts, [orphan])


def test_a_subset_of_valid_charts_is_accepted(
    profile: DatasetProfile, artifacts: tuple[AnalysisArtifact, ...]
):
    good = charts_for_artifacts(artifacts)
    report = build_report(profile, artifacts, [good[3]])
    assert report.charts == (good[3],)
    assert report.results[good[3].source_step].chart_indices == (0,)


@pytest.mark.parametrize(
    ("step", "bad_result", "where"),
    [
        (0, {"columns": "nope"}, "result.columns"),
        (3, {"group_by": ["region"], "aggregations": ["mean"], "groups": {}}, "result.groups"),
        (
            4,
            {"method": "pearson", "columns": ["a", "b"], "matrix": [[1]], "pair_counts": []},
            "result.matrix",
        ),
        (6, {"columns": ["a"], "clusters": [1]}, "result.clusters"),
        (
            1,
            {"kind": "histogram", "column": "x", "bin_edges": [1, 2], "counts": [1, 2]},
            "one more edge",
        ),
    ],
)
def test_a_malformed_result_stops_the_report_instead_of_printing_a_guess(
    profile: DatasetProfile,
    artifacts: tuple[AnalysisArtifact, ...],
    step: int,
    bad_result: dict[str, Any],
    where: str,
):
    broken = artifacts[step].model_copy(update={"result": bad_result})
    with pytest.raises(ReportError, match=where):
        build_report(profile, [broken], charts=[])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "t" * 201},
        {"source_name": "f" * 256},
        {"generated_at": "t" * 65},
    ],
)
def test_text_fields_are_validated(profile: DatasetProfile, kwargs: dict[str, Any]):
    with pytest.raises(ReportError):
        build_report(profile, [], **kwargs)


# --- text from the uploaded file never becomes markup --------------------------------------------

_HOSTILE_HEADERS = (
    "<script>alert(1)</script>",
    "<b>n|1</b>",
    'x"onmouseover="alert(1)',
    "line\nbreak",
)
_HOSTILE_KEYS = ("<img src=x onerror=alert(1)>", "[click](javascript:alert(1))", "a|b", "*bold*")


def _hostile_report() -> tuple[Report, str, str]:
    key, n1, n2, n3 = _HOSTILE_HEADERS
    quoted = ",".join('"' + h.replace('"', '""') + '"' for h in _HOSTILE_HEADERS)
    lines = [quoted]
    for i in range(24):
        key_cell = _HOSTILE_KEYS[i % 4].replace('"', '""')
        lines.append(f'"{key_cell}",{i},{(i * 7) % 11},{i % 5 + i / 10}')
    ingested = load_csv(("\n".join(lines) + "\n").encode(), "<evil>.csv")
    profile = profile_ingested(ingested)
    numeric = (n1, n2, n3)
    plan = AnalysisPlan(
        steps=(
            SummaryStatsParams(columns=numeric),
            DistributionParams(column=key),
            DistributionParams(column=n1, bins=5),
            GroupedAggregationParams(group_by=(key,), value_column=n1, aggregations=("mean",)),
            CorrelationParams(columns=numeric),
            OutlierSummaryParams(columns=numeric),
            ClusteringParams(columns=numeric, k=2),
            PcaParams(columns=numeric),
        )
    )
    artifacts = execute_plan(plan, typed_frame(ingested, profile), profile)
    report = build_report(profile, artifacts, title="<h1>x</h1>", source_name="<evil>.csv")
    return report, render_html(report), render_markdown(report)


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend((tag, name, value or "") for name, value in attrs)


def test_hostile_names_and_values_are_escaped_in_html():
    _, page, _ = _hostile_report()
    parser = _Tags()
    parser.feed(page)
    assert "script" not in parser.tags and "img" not in parser.tags and "h1" in parser.tags
    assert parser.tags.count("h1") == 1  # only the real title; the hostile "<h1>" is text
    for tag, name, value in parser.attributes:
        assert not name.startswith("on"), (tag, name)
        assert "javascript:" not in value
        if name == "href":
            assert value.startswith("#")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script" not in page and "<img" not in page
    assert "onmouseover" not in {name for _, name, _ in parser.attributes}


def test_html_is_self_contained_with_a_restrictive_content_security_policy():
    _, page, _ = _hostile_report()
    parser = _Tags()
    parser.feed(page)
    (policy,) = (
        v
        for tag, n, v in parser.attributes
        if tag == "meta" and n == "content" and "default-src" in v
    )
    assert policy == "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    urls = set(re.findall(r"https?://[^\s\"'<>]+", page))
    assert urls <= {"http://www.w3.org/2000/svg"}
    assert "<script" not in page and "<link" not in page and "@import" not in page


def test_every_chart_svg_is_well_formed_xml_even_with_hostile_labels():
    report, _, _ = _hostile_report()
    assert len(report.charts) >= 6
    for spec in report.charts:
        root = ET.fromstring(chart_svg(spec))
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert not any(name.startswith("on") for el in root.iter() for name in el.attrib)


def test_markdown_keeps_one_row_per_line_and_no_raw_html():
    _, _, text = _hostile_report()
    assert re.search(r"(?<!\\)<", text) is None  # every "<" in the file is backslash-escaped
    assert "line\nbreak" not in text
    for line in (ln for ln in text.splitlines() if ln.startswith("| ")):
        # every unescaped pipe is a cell separator, so row widths must agree within a table
        assert re.sub(r"\\.", "", line).count("|") >= 3


def test_markdown_renders_to_inert_html():
    markdown = pytest.importorskip("markdown")
    _, _, text = _hostile_report()
    rendered = markdown.markdown(text, extensions=["tables"])
    parser = _Tags()
    parser.feed(rendered)
    assert "script" not in parser.tags and "img" not in parser.tags
    assert "a" not in parser.tags  # the "[click](javascript:...)" value did not become a link
    assert not any(name.startswith("on") for _, name, _ in parser.attributes)
    assert "table" in parser.tags  # the tables were recognised, not swallowed as text


def test_markdown_table_rows_have_as_many_cells_as_their_header():
    markdown = pytest.importorskip("markdown")
    _, _, text = _hostile_report()
    for block in markdown.markdown(text, extensions=["tables"]).split("<table>")[1:]:
        table = block.split("</table>")[0]
        header = len(re.findall(r"<th[ >]", table))
        for row in re.findall(r"<tr>(.*?)</tr>", table, flags=re.S)[1:]:
            assert len(re.findall(r"<td[ >]", row)) == header


# --- helpers -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "n/a"),
        (True, "yes"),
        (False, "no"),
        (3, "3"),
        (2.0, "2"),
        (0.1 + 0.2, "0.3"),
        (-0.0, "0"),
        (-1e-9, "0"),
        (1121.197713, "1121.197713"),
        (1e20, "100000000000000000000"),
        ("text", "text"),
    ],
)
def test_fmt_value(value: object, text: str):
    assert fmt_value(value) == text


def test_escape_helpers():
    assert escape_html('<a href="x">&\'') == "&lt;a href=&quot;x&quot;&gt;&amp;&#x27;"
    assert escape_markdown("a|b\n*c* [d](e) <f> `g`") == r"a\|b \*c\* \[d\](e) \<f\> \`g\`"
    assert single_line("a\r\nb\tc\x00d") == "a b c d"


# --- the SVG renderer ----------------------------------------------------------------------------


def _spec(**changes: Any) -> ChartSpec:
    base: dict[str, Any] = {
        "kind": "bar",
        "title": "T",
        "subtitle": "S",
        "x_label": "x",
        "y_label": "y",
        "labels": ("a", "b"),
        "values": (1.0, 2.0),
        "source_step": 0,
        "operation": "distribution",
        "artifact_digest": "a" * 64,
        "source_columns": ("x",),
    }
    return ChartSpec(**{**base, **changes})


def _svg(spec: ChartSpec) -> ET.Element:
    return ET.fromstring(chart_svg(spec))


def test_bar_chart_handles_negative_and_missing_values():
    svg = chart_svg(_spec(labels=("up", "down", "gap"), values=(2.0, -3.0, None)))
    root = ET.fromstring(svg)
    rects = root.findall(".//{http://www.w3.org/2000/svg}rect")
    assert len(rects) == 2  # the missing value draws no bar
    assert "n/a" in svg and "-3" in svg and "rgb(181, 82, 59)" in svg


def test_long_labels_are_shortened_on_screen_but_kept_in_the_tooltip():
    label = "a very long column name " * 4
    svg = chart_svg(_spec(labels=(label, "b")))
    assert "\u2026" in svg
    assert escape_html(label) in svg  # full text stays available as a <title> tooltip


def test_all_zero_and_empty_charts_still_draw():
    _svg(_spec(values=(0.0, 0.0)))
    assert "No data to draw" in chart_svg(_spec(labels=(), values=()))


def test_histogram_draws_one_bar_per_bin_and_labels_the_edges():
    spec = _spec(
        kind="histogram",
        labels=("0 to 1", "1 to 2", "2 to 3"),
        values=(3.0, 0.0, 5.0),
        bin_edges=(0.0, 1.0, 2.0, 3.0),
    )
    svg = chart_svg(spec)
    assert len(ET.fromstring(svg).findall(".//{http://www.w3.org/2000/svg}rect")) == 3
    assert ">0<" in svg and ">3<" in svg


def test_heatmap_marks_undefined_cells_and_survives_many_columns():
    small = _spec(
        kind="heatmap",
        labels=("a", "b"),
        values=None,
        matrix=((1.0, None), (None, 1.0)),
    )
    svg = chart_svg(small)
    assert "#dddddd" in svg and "n/a" in svg
    names = tuple(f"c{i}" for i in range(40))
    big = _spec(
        kind="heatmap",
        labels=names,
        values=None,
        matrix=tuple(tuple(1.0 if i == j else 0.0 for j in range(40)) for i in range(40)),
    )
    root = ET.fromstring(chart_svg(big))
    assert len(root.findall(".//{http://www.w3.org/2000/svg}rect")) == 1600
