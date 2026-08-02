# Hermes Agent — Knowledge OS Release (LTS 2026-08-02)

This branch (`release/lts-2026-08-02-knowledge-os-pipeline`) is the
**LTS integration** of Hermes Agent with Knowledge OS. It carries the
audit fixes that close the operator-home-typo regression, register
the Knowledge OS `kg_query` tool, and add the workspace_runtime
plugin that wires the canonical 4-file bootstrap into the system
prompt.

## What this branch contains

- `tools/kg_query_tool.py` — ADR-015 Knowledge OS entity query tool
- `plugins/workspace_runtime/` — ADR-014 workspace runtime plugin
  (auto-discovery + canonical 4-file bootstrap on system prompt)
- `scripts/canonical_path_gate.py` — release pipeline guard that
  rejects any non-canonical absolute operator path
- Regression tests:
  - `tests/tools/test_kg_query_tool.py`
  - `tests/scripts/test_canonical_path_gate.py`
  - `tests/agent/test_wsos_bootstrap_and_kg_query_registration.py`

## Reproducibility for a fresh engineer

A clean-room bootstrap that succeeds in under 5 minutes on a Linux or
WSL machine with only `git` and `python3` available:

```bash
# 1. Clone the LTS branch
git clone --depth 20 \
  https://github.com/taras-polishchuk/hermes-agent.git \
  --branch release/lts-2026-08-02-knowledge-os-pipeline \
  hermes
cd hermes

# 2. Install in a venv
python3 -m venv venv
./venv/bin/pip install -e .
./venv/bin/pip install pytest pytest-cov

# 3. Clone the Knowledge OS repo and install its CLI
cd ..
git clone --depth 20 https://github.com/taras-polishchuk/knowledge-os.git
cd knowledge-os
python3 -m venv venv
../hermes/venv/bin/pip install -e ./knowledge-os-cli

# 4. Run the regression tests
cd ../hermes
./venv/bin/python -m pytest \
  tests/scripts/test_canonical_path_gate.py \
  tests/tools/test_kg_query_tool.py \
  tests/agent/test_wsos_bootstrap_and_kg_query_registration.py \
  -v --no-cov
# expected: 29 passed in <2s

# 5. Build a workspace vault and query it
mkdir -p /tmp/release-cert/workspace
# populate the canonical 4 files (see knowledge-os README)
cd ../knowledge-os
./venv/bin/kgctl build-workspace-runtime \
  --workspace /tmp/release-cert/workspace \
  --manifest ./runtime/workspace-sources-smoke.yaml \
  --vault /tmp/release-cert/vault \
  --report-dir /tmp/release-cert/reports \
  --actor "agent:release-cert"

# 6. Query the vault through the hermes-agent tool
cd ../hermes
KG_VAULT_PATH=/tmp/release-cert/vault \
  ./venv/bin/python -c "
import sys, os; sys.path.insert(0, '.')
import tools.kg_query_tool
import json
print(json.dumps(json.loads(tools.kg_query_tool.kg_query(
    class_name='Decision', search='', limit=5)), indent=2)[:1500])
"
```

## Architecture notes

- `agent/system_prompt.py:_build_wsos_bootstrap` discovers the
  workspace root by walking upward from the agent's cwd until a
  directory containing `GOVERNANCE/BOOTSTRAP.md` is found. This is
  the official ADR-014 discovery rule; the previous literal-suffix
  check (`cwd.name == "projects"`) was a release blocker because it
  silently bypassed the canonical 4-file load from subdirectories.
- `tools/kg_query_tool.py:_find_vault_path` resolves the
  workspace-knowledge-vault via `KG_VAULT_PATH` env var, then
  `$HOME`-relative anchors, then the canonical default. No absolute
  operator-home path is hard-coded.
- `scripts/canonical_path_gate.py` is the release pipeline guard.
  It scans any report / markdown / generated artifact for forbidden
  absolute paths and exits non-zero on any occurrence. Notable
  intentional fixtures (allowlisted) are documented in the file's
  `INTENTIONAL_FIXTURE_PATTERNS` constant.

## What is NOT in this branch

- The upstream Hermes desktop GUI / TUI / Discord / Telegram
  gateway work that landed on `main` after 2026-07-27. This branch
  is the LTS integration; the desktop work is delivered on a
  separate cycle.
- The fork's `verified-blocker-evidence-2026-07-27-v2` branch
  carries the kanban `require_block_evidence` fix that pre-dates
  this integration. It is not required for the Knowledge OS
  pipeline.

## Rollback

```bash
git checkout main
# the LTS branch is self-contained; reverting means
# moving back to a tag/commit from this branch's history.
```

## License

MIT (inherited from NousResearch/hermes-agent).
