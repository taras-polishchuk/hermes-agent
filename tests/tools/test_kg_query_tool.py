"""Tests for kg_query_tool vault path resolution.

Locks down two regressions that were easy to overlook because the tool
silently fell back to a hand-built absolute default:

  - DEFAULT_VAULT must NOT contain the operator-home typo /home/tasar.
  - _find_vault_path() must resolve through $HOME so it works for any
    operator (not just /home/taras), and via KG_VAULT_PATH overrides so
    tests can point at tmp fixtures without touching the real vault.

These tests are part of the LTS gate for the Knowledge OS → Workspace
Runtime → Hermes pipeline (see reports/knowledge-os-runtime-acceptance-2026-08-02.md).
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def _fresh_kg_query(monkeypatch):
    """Reload kg_query_tool with no cached state, env-scoped to the test."""
    monkeypatch.delenv("KG_VAULT_PATH", raising=False)
    import tools.kg_query_tool as kq
    importlib.reload(kq)
    return kq


def test_default_vault_uses_canonical_operator_home(_fresh_kg_query) -> None:
    """The hardcoded fallback path must point to /home/taras, not /home/tasar.

    The /home/tasar form was a recurring copy/paste typo that surfaced in
    the LLM wire payload (kg_query reported `"vault": "/home/tasar/..."`
    even when reading from /home/taras/...). Operators cloning the repo
    would have received a non-existent path on first invocation.
    """
    assert "/home/tasar/" not in str(_fresh_kg_query.DEFAULT_VAULT)
    assert str(_fresh_kg_query.DEFAULT_VAULT).startswith("/home/taras/")


def test_default_vault_contains_workspace_knowledge_vault(_fresh_kg_query) -> None:
    assert str(_fresh_kg_query.DEFAULT_VAULT).endswith(
        "/home/taras/projects/workspace-knowledge-vault"
    )


def test_find_vault_path_honors_kg_vault_path_env(
    tmp_path: Path, monkeypatch
) -> None:
    """When KG_VAULT_PATH points at an existing directory, the helper returns it.

    This lets tests and operators point kg_query_tool at any vault without
    touching the live /home/taras/projects/workspace-knowledge-vault.
    """
    import tools.kg_query_tool as kq
    importlib.reload(kq)
    monkeypatch.setenv("KG_VAULT_PATH", str(tmp_path))
    resolved = kq._find_vault_path()
    assert resolved == str(tmp_path)


def test_find_vault_path_never_returns_typo_anchor(monkeypatch) -> None:
    """The helper must never produce a /home/tasar/... path.

    When HOME is misspelled as ``/home/tasar`` (no such directory in the
    sandbox) and no KG_VAULT_PATH override is set, the helper still has
    the conventional ``/home/taras`` fallback. If that fallback exists
    the helper resolves through it; if it does not, the helper returns
    None. Either outcome is acceptable — but a string containing
    ``/home/tasar/`` is never acceptable, regardless of HOME.
    """
    import tools.kg_query_tool as kq
    importlib.reload(kq)
    monkeypatch.setenv("HOME", "/home/tasar")
    monkeypatch.delenv("KG_VAULT_PATH", raising=False)
    resolved = kq._find_vault_path()
    if resolved is not None:
        assert "/home/tasar/" not in resolved, (
            f"vault path leaked /home/tasar typo: {resolved}"
        )
