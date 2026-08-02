#!/usr/bin/env python3
"""kg_query - Query Knowledge OS typed entities (ADR-015).

CORRECTED per Implementation Verification: the kgctl CLI does NOT have a
'query' subcommand. This tool reads the canonical vault index.yaml directly.

Public API:
  kg_query(class_name, search, limit) -> dict
  check_kg_query_requirements() -> bool
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
    _HAVE_YAML = True
except ImportError:
    yaml = None  # type: ignore
    _HAVE_YAML = False

DEFAULT_VAULT = Path(
    os.environ.get(
        "KG_VAULT_PATH",
        "/home/taras/projects/workspace-knowledge-vault",
    )
)

ALLOWED_CLASSES = (
    "Concept",
    "Component",
    "Decision",
    "Lesson",
    "Person",
    "Project",
)

MAX_LIMIT = 50
DEFAULT_LIMIT = 10


def _scan_resolve_dir(parent_path: str, name: str) -> Optional[str]:
    """Resolve a child directory of parent_path by name using os.scandir.

    WSL/Drvfs robustness: the kernel's dcache may have a stale negative entry
    for paths under /home/taras that were previously accessed from a different
    mount namespace. os.scandir enumerates fresh; the returned path string is
    open-able even when a hand-built path fails.
    """
    try:
        for entry in os.scandir(parent_path):
            if entry.name == name:
                return entry.path
    except (OSError, ValueError):
        pass
    return None


def _find_vault_path() -> Optional[str]:
    """Locate the canonical workspace-knowledge-vault.

    Resolution order:
      1. ``$KG_VAULT_PATH`` if it exists as a directory (operators and tests
         can point the tool at any vault without touching the live one).
      2. ``$HOME`` (the operator's actual home), then ``$HOME/projects``.
      3. Conventional operator-home fallback ``/home/taras`` and
         ``/home/taras/projects`` so the tool works even when HOME is
         unset (cron jobs, bare docker containers).

    ``_scan_resolve_dir`` provides WSL/Drvfs-safe resolution by enumerating
    fresh through ``os.scandir`` instead of relying on ``Path.exists()``
    against a path that may have a stale negative dcache.
    """
    env_override = os.environ.get("KG_VAULT_PATH")
    if env_override and os.path.isdir(env_override):
        return env_override
    candidates: list[str] = []
    home = os.environ.get("HOME")
    if home:
        candidates.append(home)
        candidates.append(os.path.join(home, "projects"))
    # Conventional operator-home fallback so the tool works even when HOME
    # is unset (e.g. cron jobs, bare docker containers).
    candidates.extend(("/home/taras", "/home/taras/projects"))
    seen: set[str] = set()
    for anchor in candidates:
        if anchor in seen or not os.path.isdir(anchor):
            seen.add(anchor)
            continue
        seen.add(anchor)
        # If the anchor already names ``workspace-knowledge-vault`` directly,
        # accept it (allows tests to point at a tmp vault via env override).
        if os.path.basename(anchor.rstrip("/")) == "workspace-knowledge-vault":
            return anchor
        projects = (
            anchor
            if os.path.basename(anchor.rstrip("/")) == "projects"
            else _scan_resolve_dir(anchor, "projects")
        )
        if projects is None:
            continue
        vault = _scan_resolve_dir(projects, "workspace-knowledge-vault")
        if vault is not None:
            return vault
    return None


def _load_index(vault_path: Path) -> Dict[str, Any]:
    """Load index.yaml from the vault. Returns parsed dict or empty dict."""
    # First try the direct path - common case
    idx = vault_path / "index.yaml"
    try:
        if idx.exists():
            with open(idx, encoding="utf-8") as f:
                return yaml.safe_load(f) if _HAVE_YAML else {}
    except (OSError, ValueError):
        pass
    # Fallback: scandir-based discovery
    real_vault = _find_vault_path()
    if real_vault is None:
        return {}
    try:
        idx_resolved = _scan_resolve_dir(real_vault, "index.yaml")
        if idx_resolved is None:
            return {}
        with open(idx_resolved, encoding="utf-8") as f:
            return yaml.safe_load(f) if _HAVE_YAML else {}
    except (OSError, ValueError):
        return {}


def _norm(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize entity keys: support both kebab-case and snake_case."""
    out = dict(entity)
    if "canonical-name" in out and "canonical_name" not in out:
        out["canonical_name"] = out["canonical-name"]
    return out


def _match_class(entity: Dict[str, Any], class_name: str) -> bool:
    if not class_name:
        return True
    return str(entity.get("class", "")).lower() == class_name.strip().lower()


def _match_search(entity: Dict[str, Any], search: str) -> bool:
    if not search:
        return True
    needle = search.strip().lower()
    if not needle:
        return True
    parts: List[str] = []
    for key in ("canonical_name", "canonical-name", "name", "description",
                "aliases", "title", "summary"):
        v = entity.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v)
    return needle in " ".join(parts).lower()


def kg_query(
    class_name: str = "",
    search: str = "",
    limit: int = DEFAULT_LIMIT,
    vault_path: Optional[str] = None,
) -> Dict[str, Any]:
    if class_name and class_name not in ALLOWED_CLASSES:
        return {
            "success": False,
            "error": f"class_name must be one of {ALLOWED_CLASSES}; got {class_name!r}",
        }
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        return {
            "success": False,
            "error": f"limit must be 1..{MAX_LIMIT}; got {limit!r}",
        }

    if not _HAVE_YAML:
        return {
            "success": False,
            "error": "PyYAML is not installed in this Python environment",
        }

    target = Path(vault_path) if vault_path else DEFAULT_VAULT
    index = _load_index(target)
    if not index:
        return {
            "success": False,
            "error": f"vault index not found at {DEFAULT_VAULT / 'index.yaml'}",
        }

    entities = index.get("entities") or []
    if not isinstance(entities, list):
        return {
            "success": False,
            "error": "index.yaml does not contain an 'entities' list",
        }

    matches: List[Dict[str, Any]] = []
    for raw in entities:
        if not isinstance(raw, dict):
            continue
        entity = _norm(raw)
        if not _match_class(entity, class_name):
            continue
        if not _match_search(entity, search):
            continue
        matches.append(entity)
        if len(matches) >= limit:
            break

    return {
        "success": True,
        "entities": matches,
        "count": len(matches),
        "vault": str(DEFAULT_VAULT),
        "source": "index",
    }


def check_kg_query_requirements() -> bool:
    """Preflight: verify the vault and yaml are reachable."""
    if not _HAVE_YAML:
        return False
    real_vault = _find_vault_path()
    if real_vault is None:
        return False
    return _scan_resolve_dir(real_vault, "index.yaml") is not None


TOOL_NAME = "kg_query"
TOOLSET = "knowledge"

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Query the Knowledge OS entity vault. Search by class (Concept, "
        "Component, Decision, Lesson, Person, Project) and/or free-text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "class_name": {"type": "string", "enum": list(ALLOWED_CLASSES)},
            "search": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT},
        },
    },
}


def handler(args: Dict[str, Any], **kwargs: Any) -> str:
    return json.dumps(kg_query(
        class_name=str(args.get("class_name", "")),
        search=str(args.get("search", "")),
        limit=int(args.get("limit", DEFAULT_LIMIT)),
        vault_path=args.get("vault_path"),
    ))


# ── Registry wiring ─────────────────────────────────────────────────────────
# Until 2026-08-02 the kg_query tool was shipped as an orphan module: it
# defined TOOL_NAME / TOOL_SCHEMA / handler() but never called
# registry.register(), so discover_builtin_tools()'s AST prefilter (see
# tools/registry.py:_module_registers_tools) skipped it and the LLM never
# saw kg_query in its tool surface even when the "knowledge" toolset was
# enabled. This call closes that gap. See
# reports/knowledge-os-runtime-acceptance-2026-08-02.md for the audit
# that surfaced the missing registration.
from tools.registry import registry

registry.register(
    name=TOOL_NAME,
    toolset=TOOLSET,
    schema=TOOL_SCHEMA,
    handler=handler,
    check_fn=check_kg_query_requirements,
    emoji="🧠",
)


if __name__ == "__main__":
    import argparse
    import sys
    p = argparse.ArgumentParser()
    p.add_argument("--class", dest="class_name", default="")
    p.add_argument("--search", default="")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = p.parse_args()
    r = kg_query(class_name=args.class_name, search=args.search, limit=args.limit)
    print(json.dumps(r, indent=2))
    sys.exit(0 if r.get("success") else 1)