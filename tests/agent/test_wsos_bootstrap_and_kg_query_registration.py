"""Regression tests for the 2026-08-02 acceptance audit findings.

F1: ``_build_wsos_bootstrap`` must inject the canonical 4 files from ANY
    subdirectory of the workspace root, not just the literal basename
    ``projects`` or a path that ends with ``/projects``. The legacy
    gate silently bypassed the canonical 80KB load when the agent was
    spawned from ``projects/ai``, ``projects/career``, etc., contradicting
    ADR-014.

F2: ``kg_query`` must be registered with the tool registry. The legacy
    module shipped ``TOOL_NAME`` / ``TOOL_SCHEMA`` / ``handler()`` but
    never called ``registry.register(...)``, so the AST prefilter in
    ``tools/registry.py:_module_registers_tools`` skipped it. The LLM
    never saw kg_query in its tool surface.

Both fixes are required for the LTS gate; these tests fail loudly on
regression. See reports/knowledge-os-runtime-acceptance-2026-08-02.md.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


# ── F1: WSOS bootstrap discovery from subdirectories ──────────────────────────


@pytest.fixture
def _fresh_system_prompt():
    """Reload agent.system_prompt with no cached state for cwd-scoped tests."""
    sys.path.insert(0, "/home/taras/.hermes/hermes-agent")
    if "agent.system_prompt" in sys.modules:
        del sys.modules["agent.system_prompt"]
    return importlib.import_module("agent.system_prompt")


def test_wsos_bootstrap_loads_from_canonical_root(_fresh_system_prompt) -> None:
    """When cwd is the canonical workspace root, the canonical 4 load."""
    class A:
        pass

    agent = A()
    agent.cwd = "/home/taras/projects"
    bs = _fresh_system_prompt._build_wsos_bootstrap(agent)
    assert bs.startswith("# Workspace OS Canonical Bootstrap (ADR-014)")
    assert len(bs) > 10_000, "expected canonical 80KB load"


@pytest.mark.parametrize(
    "subdir",
    ["/home/taras/projects/ai", "/home/taras/projects/career"],
)
def test_wsos_bootstrap_loads_from_workspace_subdirectory(
    _fresh_system_prompt, subdir
) -> None:
    """Subdirectories of the canonical root must also load the canonical 4.

    This was the F1 regression: legacy code gated the load on
    ``cwd.name == "projects"`` which only matched the literal root.
    Agents spawned from ``projects/ai`` or any other subdir got an empty
    string, silently bypassing the 80KB canonical content the LLM needs.
    """
    class A:
        pass

    agent = A()
    agent.cwd = subdir
    bs = _fresh_system_prompt._build_wsos_bootstrap(agent)
    assert bs.startswith("# Workspace OS Canonical Bootstrap (ADR-014)"), (
        f"WSOS bootstrap silently bypassed for cwd={subdir!r} "
        f"(got {len(bs)} chars). This is the F1 regression."
    )


def test_wsos_bootstrap_returns_empty_outside_workspace(
    _fresh_system_prompt,
) -> None:
    """A cwd that is NOT inside the workspace must not pick up unrelated files."""
    class A:
        pass

    agent = A()
    agent.cwd = "/tmp"
    bs = _fresh_system_prompt._build_wsos_bootstrap(agent)
    assert bs == ""


# ── F2: kg_query tool registration ────────────────────────────────────────────


@pytest.fixture
def _fresh_registry():
    """Reload tools registry after ensuring kg_query_tool is importable."""
    sys.path.insert(0, "/home/taras/.hermes/hermes-agent")
    import tools.kg_query_tool  # noqa: F401 — ensure module import triggers registration
    import tools.registry as reg
    importlib.reload(reg)
    # Re-import the kg_query module so its top-level registry.register() call
    # fires against the freshly-reloaded registry. The reload above rebuilds
    # the registry module but does not re-execute side-effect imports of
    # already-loaded tool modules.
    importlib.reload(sys.modules["tools.kg_query_tool"])
    reg.discover_builtin_tools()
    return reg


def test_kg_query_is_registered_in_knowledge_toolset(_fresh_registry) -> None:
    """The kg_query tool MUST appear in the registry after discover_builtin_tools().

    Pre-2026-08-02 the module defined TOOL_NAME / TOOL_SCHEMA / handler()
    but never called registry.register(). The AST prefilter in
    tools/registry.py::_module_registers_tools then skipped the module,
    so the LLM never saw kg_query even when ``knowledge`` was enabled.
    """
    entry = _fresh_registry.registry.get_entry("kg_query")
    assert entry is not None, (
        "kg_query is not registered. The LLM cannot call it. "
        "This is the F2 regression."
    )
    assert entry.toolset == "knowledge"


def test_kg_query_registry_call_is_module_level(_fresh_registry) -> None:
    """Sanity: the registration call lives at module top level (not in a function).

    tools/registry.py::_module_registers_tools inspects AST for top-level
    ``registry.register(...)`` calls. If the call is buried in ``if __name__``
    or a function, the prefilter skips it and the tool vanishes.
    """
    import ast

    src = Path("/home/taras/.hermes/hermes-agent/tools/kg_query_tool.py").read_text()
    tree = ast.parse(src)
    has_top_level_register = False
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "register"
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "registry"
        ):
            has_top_level_register = True
            break
    assert has_top_level_register, (
        "registry.register() must be a top-level statement, not inside a "
        "function or __main__ guard, or discover_builtin_tools() will skip it."
    )