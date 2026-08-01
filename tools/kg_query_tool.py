#!/usr/bin/env python3
"""kg_query - Query Knowledge OS typed entities (ADR-015).

CORRECTED per Implementation Verification: the kgctl CLI does NOT have a
'query' subcommand. This tool reads the canonical vault index.yaml directly
using minimal YAML parsing (no PyYAML dependency).

Public API:
  kg_query(class_name, search, limit) -> dict
  check_kg_query_requirements() -> bool
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_VAULT = Path(
    os.environ.get(
        "KG_VAULT_PATH",
        "/home/tasar/projects/workspace-knowledge-vault",
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


def _parse_yaml_simple(text: str) -> Dict[str, Any]:
    """Minimal YAML loader for flat index.yaml with `entities: list[dicts]`."""
    result: Dict[str, Any] = {"entities": []}
    in_entities = False
    current_entry: Optional[Dict[str, Any]] = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if indent == 0 and stripped.startswith("entities:"):
            in_entities = True
            continue
        if not in_entities:
            m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$", stripped)
            if m:
                result[m.group(1)] = m.group(2).strip()
            continue

        if indent == 2 and stripped.startswith("- "):
            if current_entry is not None:
                result["entities"].append(current_entry)
            current_entry = {}
            rest = stripped[2:]
            if ":" in rest:
                k, _, v = rest.partition(":")
                current_entry[k.strip()] = v.strip().strip('"').strip("'")
            continue

        if current_entry is None:
            continue

        if indent >= 4 and ":" in stripped:
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip()
            if v:
                current_entry[k] = v.strip('"').strip("'")

    if current_entry is not None:
        result["entities"].append(current_entry)
    return result


def _load_index(vault_path: Path) -> Dict[str, Any]:
    index_path = vault_path / "index.yaml"
    if not index_path.exists():
        return {}
    try:
        return _parse_yaml_simple(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
    for key in ("canonical_name", "name", "description", "aliases", "title", "summary"):
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

    vault = Path(vault_path) if vault_path else DEFAULT_VAULT
    index = _load_index(vault)
    if not index:
        return {
            "success": False,
            "error": f"vault index not found at {vault / 'index.yaml'}",
        }

    entities = index.get("entities") or []
    if not isinstance(entities, list):
        return {
            "success": False,
            "error": "index.yaml does not contain an 'entities' list",
        }

    matches: List[Dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
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
        "vault": str(vault),
        "source": "index",
    }


def check_kg_query_requirements() -> bool:
    if not DEFAULT_VAULT.exists():
        return False
    return bool(_load_index(DEFAULT_VAULT))


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
