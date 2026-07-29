# HA Somfy — Pending Items

Living backlog for the HA Somfy integration. **Continuously revised**: items are added as they
surface, marked complete when verified, and deleted when no longer relevant.

- **Status:** `open` · `in-progress` · `blocked` · `parked` · `done` (move to [Completed](#completed))
- **Priority:** `H` high · `M` medium · `L` low
- **IDs are stable** — never renumber or reuse an ID, even after deletion.

> **Phase 1 is a gate.** No client or integration code is written until the protocol probe has run
> against the real gateway and the Irismo `type` string is known. Everything downstream depends on
> that one fact.

---

## 1. Protocol discovery

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| PROTO-01 | **Build `scripts/probe_uai.py`** — query-only inventory tool: auth handshake, `sdn.status.ping "*"`, then per node `sdn.status.info`, `sdn.group.get`, one `sdn.status.position`. No movement commands, ever. | H | open | Script runs end-to-end against `192.168.1.50` and writes a transcript |
| PROTO-02 | **Capture the Irismo `type` string.** The single unpublished fact this project turns on. Expect all 9 Irismo nodes to report identically (shared 1811129 hardware). | H | blocked by PROTO-01 | All 9 Irismo types recorded; agreement or disagreement documented |
| PROTO-03 | **Confirm the `params` wire shape.** Prior art disagrees: peter-dolkens sends a dict, captured traffic shows a list of single-key dicts. Settle it against the real gateway. | H | blocked by PROTO-01 | Correct shape proven by a successful response |
| PROTO-04 | **Confirm group addressing.** Hypothesis: group index N → `1.1.(N-1)`, from `somfy_controls.json` showing `ALL` = `1.1.0`. Cross-check against `sdn.group.get` membership replies. | M | blocked by PROTO-01 | Addressing scheme confirmed for all 25 groups |
| PROTO-05 | **Verify all 49 nodes answer.** Somfy's own docs warn that replies from every device are not guaranteed on a busy bus. Determine whether discovery needs retries, and how many. | M | blocked by PROTO-01 | Node count and required retry policy recorded |
| PROTO-06 | **Sanitise captures into `tests/fixtures/`.** Raw captures stay gitignored; committed fixtures carry no credentials. | H | blocked by PROTO-01 | Fixtures committed, raw captures confirmed untracked |
| PROTO-07 | **Investigate `GET /somfy_devices.json` (403).** The HTTP interface exposes richer data than telnet — raw pulse counts, limits, direction, firmware. Worth having if auth is cheap. | L | open | Auth method identified, or documented as not worth pursuing |

## 2. Capability model

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| CAP-01 | **Classifier: type string → capability**, normalised and case-insensitive, with a position probe verifying unknown types. Unknown hardware degrades to open/close/stop, never a dead slider. | H | blocked by PROTO-02 | Unit tests cover Sonesse, Irismo, and an unknown type |
| CAP-02 | **Per-motor capability override in the options flow** — force-position / force-no-position, as the manual escape hatch when detection is wrong. | M | open | Override settable per motor and respected by the entity |
| CAP-03 | **Never hardcode `supported_features`.** Guard against regression to the bug this project exists to fix. | H | open | A test fails if features are set independent of capability |

## 3. Groups

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| GROUP-01 | **25 group cover entities**, `OPEN\|CLOSE\|STOP` only — group position is not meaningful. Names already readable from `GET /somfy_groups.json`. | M | blocked by PROTO-04 | 25 group covers present and operable |
| GROUP-02 | **Per-motor group membership** recorded as an entity attribute. Static — do not let it churn. | L | blocked by PROTO-04 | Membership visible on motor entities |

## 4. Performance & fan-out

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| PERF-01 | **Change-gated state writes.** Compare before `async_write_ha_state()`. The live HA system fans every state change out to ~48 wall panels; baseline churn is 3.7 events/s. | H | open | Churn re-measured with all 74 entities live and not materially higher |
| PERF-02 | **Poll only position-capable motors**, staggered, default 60 s, configurable. The 9 Irismo are never polled. | H | open | Irismo generate zero poll traffic |
| PERF-03 | **Fast-poll only a moving motor** (~2 s) and stop as soon as it settles. | M | open | Verified by observing traffic during a single move |

## 5. Packaging & distribution

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| HACS-01 | **HACS-native layout** — `hacs.json` and `custom_components/ha_somfy/` at repo root. Do not repeat upstream's two-levels-deep mistake. | H | open | HACS validation action passes |
| HACS-02 | **CI:** hassfest + HACS validation + ruff + pytest on every push. | H | open | All four green on `main` |
| HACS-03 | **Tagged semver release** so HACS offers updates. | M | blocked by HACS-02 | `v0.1.0` released and installable via custom repo |
| HACS-04 | **Keep `requirements: []`.** Client stays vendored; no `git+https` dependency. | H | open | hassfest passes with no external requirements |

## 6. Home Assistant integration

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| HA-01 | **Config flow authenticates for real** — complete the handshake, not just open a socket. Upstream's `test_connection` only opened and closed a TCP socket. | H | open | Wrong credentials are rejected at config time |
| HA-02 | **Config flow uses auto-discovery**, not a hand-typed motor textarea. | H | blocked by PROTO-01 | 49 motors discovered without manual entry |
| HA-03 | **Single-argument step handlers.** Upstream's config flow could never complete because `async_step_motors` took two positional parameters (their issue #1). | H | open | Flow completes and creates an entry |
| HA-04 | **`diagnostics.py`** with credentials redacted — makes every future bug report cheap. | M | open | Diagnostics downloadable and secret-free |
| HA-05 | **Per-motor devices** in the device registry, not all entities hung off one gateway device. | M | open | Each motor is its own device with correct model |

## 7. Workspace & tooling

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| WORK-01 | **Orphaned `cover.*` entities.** 24 stale `restored: true` entries from a previous integration attempt remain registered. User chose to keep them, so new entities will land as `cover.roomm_shades_2` etc. and need renaming. | M | open | Entity IDs reconciled, by rename or purge |
| WORK-02 | **Rotate the gateway password.** It was shared in a chat transcript during planning. | M | open | Password rotated and HA config entry updated |
| WORK-03 | **Author a `somfy-sdn` skill** from Phase 1 findings. No skill exists anywhere for Somfy SDN, HACS/custom-component development, or telnet — verified across 74 registries / 3604 skills. | L | open | Skill written and usable |
| WORK-04 | **Git `post-commit` auto-push hook is not version-controlled** (`.git/hooks/` isn't tracked). Re-add if this repo is cloned fresh. | L | open | Hook present in any working copy in use |

## 8. Parked

Deliberately deferred — revisit only if the trade-off changes.

| ID | Item | Why parked |
|----|------|-----------|
| PARK-01 | Contribute fixes upstream to `peter-dolkens/somfy-uai` | Repo is unlicensed and unmaintained (one commit, two unanswered issues, both filed by us). Revisit if it gains a license and a maintainer. |
| PARK-02 | Support raw SDN / RS-485 without the UAI+ gateway | The gateway works and does the SDN framing. Only relevant if the UAI+ is ever removed. |

## Completed

_None yet._ Move items here with their completion date and the evidence that verified them.

---

## Maintenance process

1. **Review this file at the start of any work session**, and again before closing one out.
2. **Add** newly discovered items immediately, with a fresh stable ID, priority, and a concrete
   *Done when*. Never reuse an ID.
3. **Complete:** verify with real evidence first (per the `verify` discipline — fresh command,
   test, or MCP output, not assumption), then move the row to **Completed** with the date.
4. **Delete** items that are no longer relevant, and note the deletion in the revision log.
5. **Commit each revision** and push to `origin/main`.
6. Items large enough to need design work graduate to the the lifecycle toolkit lifecycle
   (`/new-requirement` → `docs/ai/<phase>/feature-<name>.md`) and link back to their ID here.

## Revision log

| Date | Change |
|------|--------|
| 2026-07-29 | Created. Seeded with 30 items from the project plan and the live gateway reconnaissance (ports open, 25 group names read, `somfy_devices.json` 403, 1811129 confirmed on all 9 Irismo). |
