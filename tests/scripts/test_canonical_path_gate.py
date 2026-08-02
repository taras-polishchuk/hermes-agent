"""Tests for canonical_path_gate.

Locks down the operator-home-typo / canonical-path-intrusion regressions
discovered by the 2026-08-02 acceptance audit. Without these tests, a
future copy/paste can reintroduce the typo or any other non-canonical
operator-home path into shipped artifacts.
"""

from __future__ import annotations

import os
import pathlib
from pathlib import Path

import pytest

from scripts.canonical_path_gate import (
    CANONICAL_OPERATOR_HOMES,
    Finding,
    _GENERIC_OPERATOR_HOME,
    _is_canonical,
    validate_directory,
    validate_report,
    validate_text,
)


def test_canonical_operator_homes_are_exactly_one_taras() -> None:
    """Single canonical home. If a future operator moves home, update both this list and Knowledge OS canonical-references.yaml AND CRIS pre-commit config."""
    assert CANONICAL_OPERATOR_HOMES == ("/home/taras",)


def test_validate_text_rejects_historical_typo() -> None:
    """The historical typo must always be caught, regardless of context."""
    findings = validate_text("see /home/tasar/projects for details")
    assert any("/home/tasar" in f.matched for f in findings)


def test_validate_text_rejects_typo_inside_markdown_link() -> None:
    findings = validate_text("[doc](/home/tasar/projects/ID.md)")
    assert findings, "markdown-link typo must be caught"


def test_validate_text_rejects_typo_inside_string_template() -> None:
    findings = validate_text('DEFAULT_VAULT = "/home/tasar/projects/foo"')
    assert findings, "string-literal typo must be caught"


def test_validate_text_accepts_canonical_root() -> None:
    findings = validate_text("see /home/taras/projects for details")
    assert findings == [], f"canonical path must be accepted; got {findings}"


def test_validate_text_accepts_canonical_subpath() -> None:
    findings = validate_text("/home/taras/projects/knowledge-os/runtime/workspace-sources.yaml")
    assert findings == []


def test_validate_text_rejects_other_typo_user() -> None:
    """Any /home/<non-canonical> path must be caught, not just the historical one."""
    findings = validate_text("someone left /home/alice/.config lying around")
    assert any(f.matched.startswith("/home/alice") for f in findings)


def test_validate_text_accepts_explicit_relative_paths() -> None:
    """Relative paths must never trigger the gate."""
    findings = validate_text("./projects/knowledge-os/foo.md  ../bar.md  ${HOME}/projects")
    assert findings == []


def test_is_canonical_helper() -> None:
    assert _is_canonical("/home/taras")
    assert _is_canonical("/home/taras/projects")
    assert _is_canonical("/home/taras/projects/knowledge-os")
    assert not _is_canonical("/home/tasar")
    assert not _is_canonical("/home/tasar/projects")
    assert not _is_canonical("/home/alice")
    assert not _is_canonical("/tmp")


def test_generic_operator_home_pattern_matches_typical_shapes() -> None:
    """The regex catches /home/<user> where user starts with an alpha char."""
    for s in ["/home/taras", "/home/tasar", "/home/alice", "/home/john-doe", "/home/u"]:
        assert _GENERIC_OPERATOR_HOME.search(s) is not None
    # Bare /home without a user segment should NOT match (no user part).
    assert _GENERIC_OPERATOR_HOME.search("/home") is None
    assert _GENERIC_OPERATOR_HOME.search("/home/") is None


def test_finding_format_is_actionable(tmp_path: Path) -> None:
    report = tmp_path / "r.md"
    report.write_text("# report\nsee /home/tasar/foo\n", encoding="utf-8")
    findings = validate_report(report)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.line == 2
    assert f.matched == "/home/tasar"
    formatted = f.format()
    assert str(report) in formatted
    assert "/home/tasar" in formatted
    assert "canonical" in formatted.lower()


def test_intentional_fixture_allowlist_skips_known_files(tmp_path: Path) -> None:
    """The c12 lint detector and its tests are intentional fixtures.

    They live at /lint/checks/c12_canonical_references.py and
    /tests/lint/test_c12_canonical_references.py and their entire purpose
    is to detect the operator-home-typo. Skipping them keeps the gate
    from self-flagging on every run while still catching typos in any
    NEW file an operator creates.
    """
    fake = tmp_path / "lint" / "checks" / "c12_canonical_references.py"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("# detector body with /home/tasar fixture\n", encoding="utf-8")
    findings = validate_report(fake)
    assert findings == [], "c12 detector body must be allowlisted"


def test_legacy_knowledge_os_reports_are_allowlisted(tmp_path: Path) -> None:
    """Audit reports cite the typo as historical evidence. Allowlist them.

    Per mission rules we never rewrite history; the audit reports are
    evidence of the bug we fixed, not bugs themselves. The gate must
    not block publishing them.
    """
    fake = tmp_path / "knowledge-os" / "reports" / "audit-2026-08-02.md"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("see /home/tasar/projects/foo\n", encoding="utf-8")
    assert validate_report(fake) == []


def test_new_report_with_typo_is_still_caught(tmp_path: Path) -> None:
    """The allowlist does NOT silence new reports — it whitelists specific paths only."""
    new_report = tmp_path / "reports" / "new-release-2099.md"
    new_report.parent.mkdir(parents=True, exist_ok=True)
    new_report.write_text("see /home/tasar/projects\n", encoding="utf-8")
    findings = validate_report(new_report)
    assert findings, "any new report not in the allowlist must be caught"


def test_intentional_fixture_allowlist_matches_relative_path(tmp_path: Path) -> None:
    """Regression test for the 2026-08-02 LTS-gate audit.

    The INTENTIONAL_FIXTURE_PATTERNS are written as absolute-prefix path
    fragments (e.g. ``/scripts/canonical_path_gate.py``). The gate must
    match them whether the caller passes an absolute Path or a relative
    one. Without this, the gate would flag its own docstring and tests
    on every run, defeating the purpose of the allowlist.
    """
    # The gate's own docstring contains the historical typo pattern.
    # The allowlist must match it whether the path is absolute or relative.
    relative_path = os.path.join("scripts", "canonical_path_gate.py")
    absolute_path = os.path.join("/tmp/release-cert/lts-verify/hermes", relative_path)
    assert os.path.exists(relative_path), relative_path
    assert os.path.exists(absolute_path), absolute_path

    findings_rel = validate_report(pathlib.Path(relative_path))
    findings_abs = validate_report(pathlib.Path(absolute_path))
    assert findings_rel == [], (
        f"relative path {relative_path} must be allowlisted; "
        f"got {len(findings_rel)} findings: {[f.matched for f in findings_rel]}"
    )
    assert findings_abs == [], (
        f"absolute path {absolute_path} must be allowlisted; "
        f"got {len(findings_abs)} findings: {[f.matched for f in findings_abs]}"
    )


def test_intentional_fixture_allowlist_matches_gate_test(tmp_path: Path) -> None:
    """The gate's own test file must be allowlisted (it contains the typo as fixtures)."""
    relative_path = os.path.join("tests", "scripts", "test_canonical_path_gate.py")
    absolute_path = os.path.join("/tmp/release-cert/lts-verify/hermes", relative_path)
    assert os.path.exists(relative_path), relative_path
    assert validate_report(pathlib.Path(relative_path)) == []


def test_intentional_fixture_allowlist_matches_kg_query_test(tmp_path: Path) -> None:
    """The kg_query test file is intentional (its purpose is to assert the resolver)."""
    relative_path = os.path.join("tests", "tools", "test_kg_query_tool.py")
    absolute_path = os.path.join("/tmp/release-cert/lts-verify/hermes", relative_path)
    assert os.path.exists(relative_path), relative_path
    assert validate_report(pathlib.Path(relative_path)) == []


def test_new_report_with_typo_must_be_caught_even_with_allowlist_existing(tmp_path: Path) -> None:
    """The allowlist whitelists specific paths; new files must still be caught."""
    new_evil = tmp_path / "fresh-report-2099.md"
    new_evil.write_text(
        "see " + "/" + "home" + "/" + "tas" + "ar" + "/projects/foo" + chr(10),
        encoding="utf-8",
    )
    findings = validate_report(new_evil)
    assert findings, "any new report not in the allowlist must be caught"
    assert any(
        f.matched == ("/" + "home" + "/" + "tas" + "ar") for f in findings
    )


def test_validate_report_handles_binary_or_unreadable(tmp_path: Path) -> None:
    """Binary content produces an unreadable Finding rather than crashing.

    The gate is intentionally permissive on binaries — we cannot know
    whether a byte stream is "supposed" to contain forbidden text. The
    finding is informative (operator reads the explanation) and CI can
    decide whether to fail the build based on policy.
    """
    bad = tmp_path / "binary.bin"
    bad.write_bytes(b"\x00\x01\x02 not utf-8 \xff\xfe")
    findings = validate_report(bad)
    assert len(findings) == 1
    f = findings[0]
    assert f.matched == ""
    assert "could not read artifact" in f.explanation


def test_validate_directory_recurses_and_filters(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("ok /home/taras/projects\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("bad /home/tasar/projects\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("bad /home/tasar/projects\n", encoding="utf-8")
    findings = validate_directory(tmp_path, suffixes=(".md",))
    sources = {str(f.source).rsplit("/", 1)[-1] for f in findings}
    assert sources == {"b.md"}, f"unexpected sources: {sources}"
    assert all(f.matched == "/home/tasar" for f in findings)


def test_validate_directory_returns_empty_when_clean(tmp_path: Path) -> None:
    (tmp_path / "clean.md").write_text("/home/taras/projects is canonical\n", encoding="utf-8")
    assert validate_directory(tmp_path) == []


def test_cli_strict_mode_exits_nonzero_on_typo(tmp_path: Path, monkeypatch, capsys) -> None:
    from scripts import canonical_path_gate
    bad = tmp_path / "bad.md"
    bad.write_text("see /home/tasar/foo\n", encoding="utf-8")
    rc = canonical_path_gate._cli(["--source", str(bad), "--strict"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "/home/tasar" in captured.err


def test_cli_permissive_mode_exits_zero_on_other_user(tmp_path: Path, capsys) -> None:
    """Without --strict, only the historical typo forces non-zero exit."""
    from scripts import canonical_path_gate
    other = tmp_path / "other.md"
    other.write_text("see /home/alice/foo\n", encoding="utf-8")
    rc = canonical_path_gate._cli(["--source", str(other)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "/home/alice" in captured.err  # still reported
