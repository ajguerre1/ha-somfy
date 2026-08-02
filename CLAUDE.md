# HA Somfy — Project Guide

This workspace builds **HA Somfy**, a Home Assistant custom integration (HACS-installable) for the
**Somfy Connect UAI+** gateway driving Somfy SDN blinds. Unlike the sibling `Home Assistant`
workspace — which holds specs and drives a live system through MCP — **this repo is a code
project**: the deliverable is the Python package under `custom_components/ha_somfy/`.

## The problem this solves

Irismo motors have **no SDN NodeType**. They reach the bus through Somfy bridge module P/N
1811129, which does open/close/stop and groups only — **no position feedback**. Existing
integrations hardcode `SET_POSITION` for every node, so Irismo entities render with a dead slider.
The fix is a capability model: read each node's type from the gateway, verify with a position
probe, and build entity features from actual capability. **Never reintroduce a hardcoded
`supported_features`.**

## Target system

| | |
|---|---|
| Gateway | `192.168.1.50` (example only — see note below), TCP 23 (telnet JSON-RPC) + 80 (web UI) |
| Firmware | HW 04.04 / FW 02.03.11 |
| Motors | 40 Sonesse (positional) + 9 Irismo w/ 1811129 (non-positional) |
| Groups | 25, addressed `1.1.x`, names readable from `GET /somfy_groups.json` |

> **The gateway address above is a placeholder for reference only — not a real address.**
> This repo is public, so it carries no real network addresses. The actual gateway IP lives in
> the gitignored `scripts/secrets.local.json` and in the Home Assistant config entry. Use a
> placeholder any time an address would otherwise be written down here.

## Hard constraints

- **Never send movement commands during discovery or testing without explicit confirmation.**
  These are real blinds in a occupied home. Probe scripts are query-only.
- **Panel fan-out.** The live HA system drives ~48 wall panels that receive every state change.
  Write state only on actual change; poll only position-capable motors; keep the default
  interval at 60 s. A chatty coordinator is a regression, not a detail.
- **Credentials never get committed.** Two distinct credential sets, neither ever in this repo:
  *Somfy gateway* address and user/password live in the HA config entry, mirrored for probe
  scripts in the gitignored `scripts/secrets.local.json`; *Home Assistant* API/SSH access comes from
  the **global store** `~/.ha/.env` (`. ~/.ha/load.sh`, then `ssh ha` / `$HA_URL` / `$HA_TOKEN`) —
  see `~/.ha/README.md`. Never copy either into this repo. Raw probe captures are gitignored; only
  sanitised fixtures are committed.
- **No external runtime dependencies.** `manifest.json` keeps `requirements: []`; the client is
  vendored under `custom_components/ha_somfy/uai/`.

## Development lifecycle — use AI DevKit

All work follows the **AI DevKit** lifecycle. Use `dev-lifecycle` to pick the phase, and drive each
feature through its phase docs under `docs/ai/`:

| Phase | File |
|-------|------|
| Requirements | `docs/ai/requirements/feature-<name>.md` |
| Design | `docs/ai/design/feature-<name>.md` |
| Planning | `docs/ai/planning/feature-<name>.md` |
| Implementation | `docs/ai/implementation/feature-<name>.md` |
| Testing | `docs/ai/testing/feature-<name>.md` |

Start a feature with `/new-requirement`. Supporting commands: `/review-requirements`,
`/review-design`, `/update-planning`, `/execute-plan`, `/writing-test`, `/check-implementation`,
`/code-review`, `/remember`, `/debug`, `/capture-knowledge`.

## Skills to use

- **`tdd`** — the client library and capability classifier are test-first against captured fixtures.
- **`structured-debug`** / `superpowers:systematic-debugging` — for protocol and transport faults.
- **`verify`** / `superpowers:verification-before-completion` — evidence before any "it works".
- **`home-assistant-manager`** and `mcp__home-assistant__*` — for the live HA side (entity
  verification, error logs, dashboards). Note it is config-side only; it does not cover
  custom-component development.

No skill exists anywhere for HACS/custom-component development, Somfy SDN, or telnet — verified
across 74 registries. Consider authoring one from this project's findings.

## Pending items — the backlog

Pending work is tracked in **`docs/ai/planning/backlog.md`**, a living document. **Review it at the
start of any work session, and again before closing one out.** Stable IDs, never reused. Mark items
complete only with real evidence.

## Memory

Before non-trivial work, search: `ai-devkit memory search --query "<topic>" --scope project:ha-somfy`.
Store durable knowledge with `/remember` or:
`ai-devkit memory store --title "..." --content "..." --tags "..." --scope "project:ha-somfy"`.
Shared SQLite DB at `~/.ai-devkit/memory.db`.

> On Windows, run `memory store` via the **Bash** tool, not PowerShell — PowerShell mangles long
> `--content` arguments and produces a misleading "must be at least 50 characters" error.

## Testing

- **Unit:** `pytest` with `pytest-homeassistant-custom-component`, replaying captured protocol
  fixtures. No hardware required.
- **Lint:** `ruff`.
- **CI:** hassfest + HACS validation + ruff + pytest on every push.
- **Live:** movement is validated one motor at a time — one Sonesse, then one Irismo, then one
  group, then the fleet.

## Git sync

Public remote `origin` → `ajguerre1/ha-somfy`. **After every local commit, push to `origin/main`.**
Pause and confirm before pushing only when the push carries specific risk — secrets in the diff, a
force-push, or rewriting already-pushed history.

**This is a manual step, not a hook** (WORK-04). Automating it with `post-commit` was considered and
rejected: an unconditional auto-push cannot make the judgment the previous sentence requires, and it
would push a commit containing credentials before anyone could stop it. `.git/hooks/` is also
untracked, so a hook would silently not exist in a fresh clone. Push deliberately instead.

Releases are tagged semver; HACS offers updates from GitHub releases.
