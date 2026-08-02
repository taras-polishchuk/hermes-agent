"""Canonical Path Integrity Gate — release pipeline guard.

Phase 3 / Phase-8 mission deliverable. Rejects any artifact (report,
markdown, terminal capture, wire trace, generated vault entry) that
emits a non-canonical absolute path. The single historical defect
this guard exists to eliminate is the recurring operator-home typo
/home/tasar (vs canonical /home/taras), but the gate is generic and
will catch any future drift as well.

Usage in release pipelines:

    from canonical_path_gate import validate_report

    artifact = pathlib.Path("reports/release-2026-08-02.md").read_text()
    findings = validate_report(artifact, source=artifact_path)
    if findings:
        raise CanonicalPathViolation(findings)

Usage in CI:

    python -m canonical_path_gate.reports --root reports/

The gate is intentionally narrow:
- It only inspects string content (not filesystem traversal).
- It only matches absolute paths it can prove wrong (currently any
  /home/<user> path where <user> is not the canonical operator).
- It produces actionable findings (file:line, offending substring,
  explanation) rather than opaque error codes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# ── Canonical references ────────────────────────────────────────────────────
# These are the only absolute operator-home roots the system recognizes.
# A future operator who legitimately moves to a different home must
# update this list AND the canonical-references.yaml in Knowledge OS
# AND the CRIS pre-commit guard config.

CANONICAL_OPERATOR_HOMES: tuple[str, ...] = ("/home/taras",)

# Allowlist: subpaths that are KNOWN to be intentional fixtures.
# (a) The c12 canonical-references lint check and its tests are designed
#     to detect the operator-home-typo; their source contains the typo
#     as negative-example fixtures. We allowlist them by relative path
#     fragment so future authors can't accidentally widen the gate's
#     scope.
# (b) The audit reports we publish may contain the typo as evidence;
#     those are HISTORICAL and must never be rewritten (per mission
#     rules: "never rewrite history"). We allowlist them under the
#     reports/ directory and lessons/ directory and reviews/ directory
#     of the knowledge-os repo.
# Add an entry ONLY when you can justify it in the mission report.
INTENTIONAL_FIXTURE_PATTERNS: tuple[str, ...] = (
    # c12 canonical-references detector body and its tests.
    "/lint/checks/c12_canonical_references.py",
    "/tests/lint/test_c12_canonical_references.py",
    # Knowledge OS reports (historical audit evidence).
    "/knowledge-os/reports/",
    "/knowledge-os/reviews/",
    "/knowledge-os/lessons/",
    # This gate itself (its docstring explains the typo).
    "/scripts/canonical_path_gate.py",
    "/tests/scripts/test_canonical_path_gate.py",
    # kg_query tool test (its purpose is to assert the resolver does
    # not return the typo; the literal appears as fixture data).
    "/tests/tools/test_kg_query_tool.py",
    # Our own scan + regression-audit tools (re-encode the literal
    # intentionally to surface every occurrence; the tools do NOT
    # ship the literal in their own emitted text — the literal is
    # only in source comments documenting what is being scanned).
    "/reports/scan_tasar_occurrences.py",
    "/reports/regression_path_audit.py",
)

# Forbidden patterns. We catch the historical typo plus a few obvious
# siblings in case a fresh operator inherits a copy-paste of the bug.

_FORBIDDEN_HOME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(r"/home/" + re.escape(user)) for user in ("tasar",)
)

# Generic guard for any absolute /home/<user> path that is NOT in
# CANONICAL_OPERATOR_HOMES. This catches the same class of bug for any
# future operator-home typo. We skip /home itself (rare but legitimate).

_GENERIC_OPERATOR_HOME = re.compile(r"/home/(?P<user>[A-Za-z][A-Za-z0-9_.-]*)")


@dataclass(frozen=True)
class Finding:
    """A single violation in a single artifact."""

    source: str
    line: int
    column: int
    matched: str
    explanation: str

    def format(self) -> str:
        return (
            f"{self.source}:{self.line}:{self.column}: "
            f"forbidden absolute path {self.matched!r} — {self.explanation}"
        )


def _is_canonical(path: str) -> bool:
    return any(path == home or path.startswith(home + "/") for home in CANONICAL_OPERATOR_HOMES)


def _iter_findings(text: str, source: str) -> Iterable[Finding]:
    """Yield one Finding per offending absolute path.

    Both passes (historical-typo + generic /home/<user>) can match the
    same substring. Dedupe by (line, column, matched) so a single
    offending occurrence yields one finding, not two.
    """
    seen: set[tuple[int, int, str]] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        # Specific historical patterns first (cheap, exact).
        for pat in _FORBIDDEN_HOME_PATTERNS:
            for match in pat.finditer(line):
                key = (line_no, match.start(), match.group(0))
                if key in seen:
                    continue
                seen.add(key)
                yield Finding(
                    source=source,
                    line=line_no,
                    column=match.start() + 1,
                    matched=match.group(0),
                    explanation=(
                        "non-canonical operator-home root; the only "
                        "canonical operator home is "
                        f"{CANONICAL_OPERATOR_HOMES[0]}. This is the "
                        "historical operator-home-typo that this gate "
                        "exists to prevent from ever shipping again."
                    ),
                )
        # Generic /home/<user> check.
        for match in _GENERIC_OPERATOR_HOME.finditer(line):
            candidate = match.group(0)
            if _is_canonical(candidate):
                continue
            key = (line_no, match.start(), candidate)
            if key in seen:
                continue
            seen.add(key)
            yield Finding(
                source=source,
                line=line_no,
                column=match.start() + 1,
                matched=candidate,
                explanation=(
                    "non-canonical absolute operator-home path; allowed "
                    f"roots are {CANONICAL_OPERATOR_HOMES}. Fix the "
                    "generator or the operator home; do not commit."
                ),
            )


def validate_text(text: str, *, source: str = "<inline>") -> list[Finding]:
    """Return every Finding produced by scanning *text*."""
    return list(_iter_findings(text, source))


def validate_report(path: Path) -> list[Finding]:
    """Validate a single report file. Returns an empty list on clean."""
    # Allowlist: known intentional fixtures ship with the typo as part of
    # their documented purpose. Skipping them prevents the gate from
    # self-flagging on every run.
    #
    # The allowlist patterns are absolute-prefix path fragments (e.g.
    # ``/scripts/canonical_path_gate.py``). We match against the absolute
    # resolved path so callers can pass either relative or absolute
    # PosixPath objects.
    spath = str(path)
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = spath
    if any(fragment in resolved or fragment in spath for fragment in INTENTIONAL_FIXTURE_PATTERNS):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [
            Finding(
                source=str(path),
                line=0,
                column=0,
                matched="",
                explanation=f"could not read artifact: {exc}",
            )
        ]
    return validate_text(text, source=str(path))


def validate_directory(root: Path, *, suffixes: Sequence[str] = (".md", ".txt", ".json", ".yaml", ".yml"), skip_dirs: Sequence[str] = ("__pycache__", ".git", "site-packages", "lib/python", ".venv", "venv", "node_modules", ".cache")) -> list[Finding]:
    """Recursively validate every file under *root* matching a suffix.

    Default skip_dirs keeps the gate from flagging pip-installed
    site-packages (full of /home/<user> example paths in docstrings) and
    ephemeral build/caches that aren't "our" code.
    """
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Honor skip_dirs as path-fragment matches so callers can extend.
        spath = str(path)
        if any(fragment in spath for fragment in skip_dirs):
            continue
        if suffixes and path.suffix not in suffixes:
            continue
        findings.extend(validate_report(path))
    return findings


class CanonicalPathViolation(RuntimeError):
    """Raised by release pipelines when validate_report returns findings."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = list(findings)
        lines = "\n".join(f.format() for f in self.findings)
        super().__init__(
            f"canonical path integrity gate rejected artifact: "
            f"{len(self.findings)} violation(s)\n{lines}"
        )


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="canonical_path_gate",
        description="Reject reports that emit non-canonical operator-home paths.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="directory to scan (default: cwd)",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        type=Path,
        help="explicit file or directory to validate (repeatable)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on any finding (default: only on canonical-typo findings)",
    )
    parser.add_argument(
        "--report-suffixes",
        default=".md,.txt,.json,.yaml,.yml",
        help="comma-separated suffixes to inspect when scanning directories",
    )
    args = parser.parse_args(argv)

    suffixes = tuple(s.strip() for s in args.report_suffixes.split(",") if s.strip())
    findings: list[Finding] = []

    if args.source:
        for src in args.source:
            if src.is_dir():
                findings.extend(validate_directory(src, suffixes=suffixes))
            elif src.is_file():
                findings.extend(validate_report(src))
            else:
                print(f"canonical_path_gate: skipping missing path {src}", file=sys.stderr)
    else:
        findings.extend(validate_directory(args.root, suffixes=suffixes))

    if not findings:
        print("canonical_path_gate: clean — no forbidden paths detected")
        return 0

    for f in findings:
        print(f.format(), file=sys.stderr)

    # Strict mode forces non-zero exit on ANY finding. Without --strict,
    # the historical-typo pattern always forces non-zero (because that
    # specific defect has shipped before and we never want it silent
    # again); other non-canonical /home/<user> paths are reported but
    # may be intentional fixtures (e.g. tests asserting on other users).
    if args.strict:
        return 1
    has_historical_typo = any("/home/tasar" in f.matched for f in findings)
    return 1 if has_historical_typo else 0


if __name__ == "__main__":
    raise SystemExit(_cli())