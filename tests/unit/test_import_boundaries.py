"""Static import-boundary checks derived from docs/ARCHITECTURE.md."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "ai_data_analyst"

PROJECT_ROOT = "ai_data_analyst"
M1_MODULES = frozenset({"ingestion", "profiling", "analysis", "visualization", "reporting", "chat"})
SHARED_MODULES = frozenset({"models", "security", "evaluation"})
SQL_MODULE = "sql_agent"
UI_MODULE = "ui"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _submodule(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def _is_project(target: str) -> bool:
    return target == PROJECT_ROOT or target.startswith(f"{PROJECT_ROOT}.")


def _resolve_relative(package: str, level: int, imported: str | None) -> str | None:
    parts = package.split(".")
    if level < 1 or level > len(parts):
        return None
    base = parts[: len(parts) - (level - 1)]
    if imported is not None:
        base = [*base, imported]
    if not base:
        return None
    return ".".join(base)


def _scan_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_name = _module_name(path)
    is_package = path.name == "__init__.py"
    package = module_name if is_package else module_name.rpartition(".")[0]

    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = _resolve_relative(package, node.level, node.module)
                if target is not None:
                    found.append((target, node.lineno))
            elif node.module:
                found.append((node.module, node.lineno))
    return found


def _check_rules(source_module: str, imports: list[tuple[str, int]]) -> list[str]:
    source = _submodule(source_module)
    violations: list[str] = []
    for target, line in imports:
        if source != UI_MODULE and (target == "streamlit" or target.startswith("streamlit.")):
            violations.append(f"{source_module}:{line}: only ui/ may import streamlit")
        if not _is_project(target):
            continue
        target_top = _submodule(target)
        if source in M1_MODULES and target_top == SQL_MODULE:
            violations.append(f"{source_module}:{line}: {source} must not import {target_top}")
        if source == SQL_MODULE and target_top in M1_MODULES:
            violations.append(f"{source_module}:{line}: {source} must not import {target_top}")
        if source in SHARED_MODULES and target_top not in SHARED_MODULES and target_top != "":
            violations.append(
                f"{source_module}:{line}: shared module {source} must not import {target_top}"
            )
    return violations


def test_source_tree_respects_import_boundaries():
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        violations.extend(_check_rules(_module_name(path), _scan_imports(path)))
    assert violations == []


def test_relative_imports_resolve_to_project_modules():
    assert _resolve_relative("ai_data_analyst.evaluation", 2, "models") == "ai_data_analyst.models"
    assert (
        _resolve_relative("ai_data_analyst.security", 1, "limits")
        == "ai_data_analyst.security.limits"
    )
    assert _resolve_relative("ai_data_analyst.security", 2, "models") == "ai_data_analyst.models"
    assert _resolve_relative("ai_data_analyst", 2, "models") is None


def test_checker_rejects_forbidden_edges():
    assert _check_rules("ai_data_analyst.profiling.profile", [("ai_data_analyst.sql_agent", 3)])
    assert _check_rules("ai_data_analyst.sql_agent.executor", [("ai_data_analyst.analysis", 5)])
    assert _check_rules("ai_data_analyst.security.limits", [("ai_data_analyst.ingestion.csv", 1)])
    assert _check_rules("ai_data_analyst.evaluation.comparison", [("ai_data_analyst.ui.page", 2)])
    assert _check_rules("ai_data_analyst.models", [("ai_data_analyst.chat", 1)])
    assert _check_rules("ai_data_analyst.profiling.profile", [("streamlit", 1)])
    assert _check_rules("ai_data_analyst.models", [("streamlit.runtime", 1)])


def test_checker_allows_expected_edges():
    assert not _check_rules(
        "ai_data_analyst.profiling.profile",
        [("ai_data_analyst.models", 1), ("ai_data_analyst.security", 2), ("pandas", 3)],
    )
    assert not _check_rules("ai_data_analyst.sql_agent.executor", [("ai_data_analyst.models", 1)])
    assert not _check_rules("ai_data_analyst.ui.page", [("streamlit", 1)])
    assert not _check_rules(
        "ai_data_analyst.security.limits", [("ai_data_analyst.models", 1), ("pydantic", 2)]
    )
    assert not _check_rules(
        "ai_data_analyst.evaluation.comparison",
        [("ai_data_analyst.models", 1), ("ai_data_analyst.security.limits", 2), ("pydantic", 3)],
    )
