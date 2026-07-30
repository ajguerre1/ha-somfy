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

**PROTO-01 through PROTO-06 are done** — see [Completed](#completed) and the findings doc
[`docs/ai/design/feature-uai-protocol.md`](../design/feature-uai-protocol.md).

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| AREA-01 | **Reassign the 24 group entities to their real rooms.** They inherit the gateway device's area (`it_equipment`). Cosmetic, and better done after the dashboard migration so entity IDs are settled first. | L | open | Each group entity sits in its own room's area |

## 2. Capability model

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| CAP-01 | **Classifier: type string → capability**, normalised and case-insensitive, with a position probe verifying unknown types. Unknown hardware degrades to open/close/stop, never a dead slider. **Match `sdn module`, not `irismo`** — see CAP-05. | H | open | Unit tests cover `Sonesse 50DC`, `Sonesse 30`, `SDN Module`, and an unknown type |
| CAP-04 | **Reject `bool` before any numeric position check.** `isinstance(False, int)` is `True` in Python, so the gateway's `{"result":false}` reads as position 0. This bug was found and fixed in the probe itself; it must not reappear in the client. | H | open | A test asserts `False` is not accepted as a position |
| CAP-05 | **Do not classify on the string `irismo`** — it never appears on the wire. The gateway reports the 1811129 bridge as `SDN Module`. A regression here silently breaks all 9 Irismo. | H | open | Test asserts `SDN Module` → non-positional |
| CAP-06 | **Treat `false` position as "temporarily unknown", not "non-positional".** A Sonesse must never have its feature set flap because one poll failed. | H | open | Test asserts capability is stable across a `false` reading |
| CAP-02 | **Per-motor capability override in the options flow** — force-position / force-no-position, as the manual escape hatch when detection is wrong. | M | open | Override settable per motor and respected by the entity |
| CAP-03 | **Never hardcode `supported_features`.** Guard against regression to the bug this project exists to fix. | H | open | A test fails if features are set independent of capability |

## 3. Groups

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| GROUP-01 | **Group cover entities**, `OPEN\|CLOSE\|STOP` only — group position is not meaningful. Address formula confirmed: `"0101" + f"{index:02X}"`. | M | open | Group covers present and operable |
| GROUP-02 | **Per-motor group membership** recorded as an entity attribute. Static — do not let it churn. | L | open | Membership visible on motor entities |
| GROUP-03 | **Group 1 `ALL` is omitted** (owner's decision). Only the 24 member-bearing groups become entities. | M | open | Discovery skips `010101` |
| GROUP-04 | **Groups inherit their members' capability.** Every group on this bus is homogeneous — 4 are all-Irismo (`RoomG SH`, `RoomI B/O`, `RoomI SH`, `RoomD SH`), the rest all-Sonesse. Guard the mixed case anyway: fall back to the least-capable member. | M | open | Test covers homogeneous and mixed groups |

## 3b. Hardware findings — surfaced by the Phase 1 probe

Real-world conditions the integration must tolerate. None of these are code defects.

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| HW-01 | **Two motors reply `false` to position, and both are confirmed physically faulty** — `07753E` "RoomB SH 2" and `077537` "RoomB B/O 3", both disconnected/faulty pending repair. All 38 healthy positional motors return a number, so the correlation is 2 for 2. **`false` therefore signals a motor-side fault, not a configuration gap** — a useful diagnostic, and confirmation that capability must come from the type string so a faulty Sonesse is never silently reclassified as an Irismo. No action expected; the integration shows position as unknown without demoting capability. | L | parked | Entity handles it gracefully (covered by CAP-06) |
| HW-03 | **Void — there is no duplicate name.** `136E33` is `RoomA SH 2`, not `RoomA B/O 2`; confirmed by the owner's web UI, the gateway's HTTP `LABEL`, and a later telnet read. The 14:04 capture recorded the wrong name while that node's group membership (`010103` = `RoomA SH`) already said otherwise — the contradiction was in the data and went unchecked. Nothing to rename. The uniqueness guard stays as a defensive measure. See §10 of the protocol findings. | M | done | — |
| NAME-01 | **Names resolved from two sources.** `sdn.status.info` answers a *first* read with a name synthesised from group membership when the gateway has not yet read the device's own label; the query triggers that read and a second call returns the truth. Discovery therefore reads each node twice and prefers the gateway's HTTP `LABEL`. Verified live: 49 nodes, 0 unnamed, 46 from HTTP and 3 from the second telnet read — including `40FD89`, which HTTP never served. Matters because entity IDs derive from the name and are assigned once. | H | done | — |

## 4. Performance & fan-out

> **Measured 2026-07-29:** 149 requests in **5.0 s** total, mean 0.03 s, max 0.53 s, zero retries.
> The bus is *fast*. The planning assumption that the gateway is slow under bulk query was wrong;
> polling all 40 positional motors costs roughly **1.2 s**.

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| PERF-01 | **Change-gated state writes.** Compare before `async_write_ha_state()`. The live HA system fans every state change out to ~48 wall panels; baseline churn is 3.7 events/s. | H | open | Churn re-measured with all entities live and not materially higher |
| PERF-02 | **Poll only position-capable motors**, staggered, default 60 s, configurable. The 9 Irismo are never polled. | H | open | Irismo generate zero poll traffic |
| PERF-04 | **`iot_class` is `local_polling`, not `local_push`.** Zero unsolicited notifications appeared in 149 requests, contradicting prior art's `local_push` claim. | M | open | manifest.json declares `local_polling` |

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
| WORK-01 | **DO NOT DELETE the 24 existing `cover.*` entities.** They are **not** orphans — owner confirmed they are live entities bridged into HA via **Homebridge**, merely `unavailable` at the time of inspection. An earlier reading of this backlog wrongly identified them as leftovers from a failed integration and recommended purging them; deleting them would have destroyed working configuration. `restored: true` plus a 1:1 name match to the 24 groups is **not** evidence an entity is dead — here it meant the same groups were already reaching HA by another route. Owner's instruction: rename these to `*_2` rather than remove them. | H | open | The 24 Homebridge entities are preserved; naming reconciled per OPEN-01 |
| OPEN-01 | **Resolved:** new entities land with their own IDs; references get migrated. No renaming of the Homebridge entities is needed — a collision check confirmed none of the 24 predicted new IDs already exists, so Home Assistant will not append `_2`. Mapping documented in [`entity-migration-map.md`](entity-migration-map.md). | H | done | — |
| MIGRATE-01 | **Re-verify the predicted entity IDs** against the live registry immediately after the config entry is created, before editing any dashboard. The new column in the migration map is derived from a slugify rule, not observed. | H | open | All 24 new IDs confirmed against the entity registry |
| MIGRATE-02 | **Inventory every reference** to the 24 old entity IDs across 68 dashboards, plus automations, scripts and scenes. Produce a per-dashboard list before changing anything. | H | blocked by MIGRATE-01 | Complete reference inventory produced and reviewed |
| MIGRATE-03 | **Rewrite references old → new**, one dashboard at a time with verification between each, after taking backups. Leave the Homebridge entities in place as a fallback until the new ones are proven. | H | blocked by MIGRATE-02 | All references migrated and each dashboard verified |
| MIGRATE-04 | **Fix the four Irismo entities' position calls.** `cover.roomg_living_drapes`, `cover.roomi_blackouts`, `cover.roomi_drapes` and `cover.roomd_hallway_drapes` currently claim `supported_features: 15` via Homebridge, including `SET_POSITION` — a claim that has always been false, since Irismo has no position feedback. After migration they correctly report `11`. Any `cover.set_cover_position` call on them is a no-op today and must become open/close. | H | blocked by MIGRATE-02 | No `set_cover_position` calls remain against the four Irismo groups |
| MIGRATE-05 | **`077537` "RoomB B/O 3" is out of service by design — no action needed.** Owner physically disconnected it pending repair and removed it from `RoomB B/O`, so that group correctly has 2 members and `cover.roomb_b_o` drives 2 of 3. When repaired: add it back to the group in the UAI+ web UI and reload the integration; discovery picks up the membership with no code change. Until then it exists only as a disabled-by-default motor entity, generating no traffic. | L | parked | Motor repaired, re-added to the group, and discovery reflects 3 members |
| WORK-03 | **Author a `somfy-sdn` skill** from Phase 1 findings. No skill exists anywhere for Somfy SDN, HACS/custom-component development, or telnet — verified across 74 registries / 3604 skills. | L | open | Skill written and usable |
| WORK-04 | **Git `post-commit` auto-push hook is not version-controlled** (`.git/hooks/` isn't tracked). Re-add if this repo is cloned fresh. | L | open | Hook present in any working copy in use |
| WORK-05 | **Icon works in Home Assistant. The HACS store list cannot be fixed from this repo — parked.** Confirmed on the live system after installing v0.1.1: the icon renders in *Add Integration*, proving `brand/icon.png` and the local API work. It does **not** render in the HACS store list. Cause: HACS ships its own bundled frontend pinned to an **older** `homeassistant-frontend` submodule (`3ffbd43`) whose `brandsUrl()` builds a CDN URL directly — `https://brands.home-assistant.io/_/{domain}/dark_icon.png` — with no local-API path and no token. That URL returns the grey placeholder for `ha_somfy`, verified. Current HA frontend instead returns `/api/brands/integration/{domain}/…`, which is why HA's own UI works. **No custom integration created after the brands repo closed to them can have a HACS store-list icon** until HACS updates its vendored frontend. Cosmetic only, and confined to that one list. | L | parked | HACS updates its bundled frontend; nothing actionable here |

## 8. Parked

Deliberately deferred — revisit only if the trade-off changes.

| ID | Item | Why parked |
|----|------|-----------|
| PARK-01 | Contribute fixes upstream to `peter-dolkens/somfy-uai` | Repo is unlicensed and unmaintained (one commit, two unanswered issues, both filed by us). Revisit if it gains a license and a maintainer. |
| PARK-02 | Support raw SDN / RS-485 without the UAI+ gateway | The gateway works and does the SDN framing. Only relevant if the UAI+ is ever removed. |

## Completed

| ID | Item | Done | Evidence |
|----|------|------|----------|
| PROTO-01 | Built `scripts/probe_uai.py`, query-only with an enforced allowlist | 2026-07-29 | Ran clean against all 49 nodes; `tests/test_probe_safety.py` proves 13 mutating/unknown methods are refused and 4 read-only ones permitted |
| PROTO-02 | **Irismo reports `type: "SDN Module"`** — all 9, identically. The string `irismo` never appears; the gateway names the 1811129 bridge, not the motor. All 9 refuse position with `{"error":-32600}` | 2026-07-29 | `tests/fixtures/bus_inventory.json` — histogram `Sonesse 50DC=28, Sonesse 30=12, SDN Module=9` |
| PROTO-03 | `params` is a **list of single-key dicts**, not a bare dict | 2026-07-29 | Runtime shape detection returned `list`; 149 successful requests |
| PROTO-04 | Group address = `"0101" + f"{index:02X}"`, index 1-based from `somfy_groups.json`. Group 1 `ALL` is a broadcast with no stored membership | 2026-07-29 | All 24 member-bearing groups matched by name, e.g. `010106`→`RoomG B/O`, `010119`→`RoomK SH` |
| PROTO-05 | Bus is fast and reliable: 149 requests in 5.0 s, mean 0.03 s, **zero retries**. One transient single-node dropout observed → HW-02 | 2026-07-29 | `timings` in probe output; 6 discovery passes |
| PROTO-06 | Sanitised fixtures committed; raw captures gitignored | 2026-07-29 | `tests/fixtures/*.json` committed; credential scan across all committable files came back clean |
| WORK-06 | Stale `ajguerre1/brands` fork deleted (created for the rejected PR #10871) | 2026-07-29 | `gh api repos/ajguerre1/brands` → **404**; `gh repo list ajguerre1 --fork` returns nothing; `ha-somfy` confirmed intact and not a fork |
| **PROTO-08** | **Position polarity confirmed correct.** `GATEWAY_POSITION_IS_INVERTED = True` stands; Somfy 0 = open, HA 0 = closed. Settled with **zero movement**. | 2026-07-29 | Live entities read closed for all four bathroom/toilet shades and both guest bed blackouts, open for everything else; owner confirmed that matches the physical blinds |
| **CAP-03 (live)** | **The Irismo fix verified on real hardware.** Four all-Irismo groups report `supported_features: 11` with `assumed_state: true` and state `unknown`; all twenty Sonesse groups report `15` with real positions. | 2026-07-29 | `batch_get_state` across all 24 group entities |
| MIGRATE-01 | Entity IDs re-verified against the live registry | 2026-07-29 | All 24 observed as `cover.somfy_uai_*` — HA prefixes the gateway device name, so the predicted `cover.roomb_sh` form was wrong. Map corrected; member counts match the Phase 1 probe exactly |
| CAP-01 | Classifier maps type string → capability, probing unknown types | 2026-07-29 | `tests/test_models.py`; replaying the real 49-node inventory splits exactly 40 positional / 9 non-positional with 0 unknown |
| CAP-04 | `bool` rejected before any numeric position check | 2026-07-29 | `test_bool_is_never_a_position`; the probe's own version of this bug was found and fixed |
| CAP-05 | Classifier matches `SDN Module`, not `irismo` | 2026-07-29 | `test_sdn_module_is_non_positional`; `irismo` retained only as a defensive alias |
| CAP-06 | A `false` reading leaves capability untouched | 2026-07-29 | `test_the_false_position_node_keeps_its_capability` against real node `07753E` |
| PERF-02 | Only position-capable motors are polled | 2026-07-29 | `SomfyCoordinator._async_update_data` skips non-positional nodes; the 9 Irismo generate no poll traffic |
| PERF-04 | `iot_class` declared `local_polling` | 2026-07-29 | `manifest.json`; zero unsolicited notifications were seen in 149 probe requests |
| GROUP-03 | Group 1 `ALL` omitted from discovery | 2026-07-29 | `UaiClient.async_get_groups` filters it; `test_discovery_skips_the_all_group` |
| HW-02 | Transient node dropout tolerated | 2026-07-29 | `SomfyCoordinator.async_discover` requires 3 consecutive misses before dropping a node |
| CAP-03 | `supported_features` never hardcoded | 2026-07-29 | CI: `test_irismo_does_not_advertise_set_position` and `test_sonesse_does_advertise_set_position` both pass |
| GROUP-01 | Group cover entities, open/close/stop | 2026-07-29 | CI: `test_all_irismo_group_has_no_position_slider`, `test_all_sonesse_group_has_a_position_slider` |
| GROUP-04 | Groups inherit least-capable member | 2026-07-29 | CI: `test_mixed_group_falls_back_to_least_capable` |
| PERF-01 | Change-gated state writes | 2026-07-29 | CI: `test_state_is_written_only_when_something_changed` — 3 refreshes, 1 write |
| HA-01 | Config flow authenticates for real | 2026-07-29 | CI: `test_bad_credentials_are_rejected` |
| HA-02 | Config flow uses auto-discovery | 2026-07-29 | CI: `test_confirm_step_reports_the_capability_split`; no hand-typed motors anywhere |
| HA-03 | Single-argument step handlers | 2026-07-29 | CI: `test_flow_completes_and_creates_an_entry` — the flow reaches CREATE_ENTRY |
| HA-04 | `diagnostics.py` with credentials redacted | 2026-07-29 | `async_get_config_entry_diagnostics` redacts username and password |
| HA-05 | One device per motor | 2026-07-29 | CI: `test_each_motor_is_its_own_device_showing_its_model` |
| **PERF-03** | **A moving cover updates promptly instead of waiting up to 60 s.** `async_follow_movement` polls only the nodes just commanded, every 2 s, dropping each after 3 unchanged reads (~6 s, covering motor start-up), with a 120 s ceiling. Non-positional nodes are filtered out entirely, so the nine Irismo add no traffic; entities stay change-gated, so a no-op poll writes nothing. | 2026-07-29 | 7 coordinator tests in CI, plus owner confirmation on live hardware: "the lag is gone, it updates nicely" |
| **HW-04** | **Discovery warns when a node's name points at a group it is not in.** Narrow by design: whitespace and case are ignored, so `RoomI SH 1` in `RoomI SH` is silent, and a name resembling no other group, like `RoomD Hall SH` in `RoomD SH`, is silent too. Only a name matching *another existing group* warns — which is exactly the `136E33` case. | 2026-07-29 | `find_name_group_conflicts` + 7 tests, including one asserting the current 49-node fleet produces **zero** warnings |
| **PROTO-07** | **Answered — the endpoints do unlock, but are not worth adopting.** Owner spotted that `pilot.htm` has its own password. Auth is `GET /password.cgi?VERIFY=<web password>`, a separate credential from telnet, and it sets **no cookie** — the session is IP-bound. Afterwards `somfy_devices.json` returns all 49 labels in **one** request, including the two nodes the per-node endpoint never served, and `somfy_presets.json` returns 16 slots per node. **All 16 are empty on all 49 nodes**, so there is no preset feature to build. Not adopted: discovery already names all 49 correctly without it, and adopting would add a second credential to the config flow for every user plus IP-bound session handling. | 2026-07-30 | `scripts/probe_web_session.py`; 49 devices, 49 labels, 0 presets |
| **PROTO-09** | **The `sdn.` prefix is optional.** `status.info`, `status.position` and `group.get` return payloads identical to their prefixed forms. Usable as a fallback; no reason to switch. | 2026-07-29 | `scripts/probe_open_questions.py`, all three pairs identical |
| **LIVE-01** | **Movement verified on real hardware — both paths.** Sonesse: `RoomM SH` (group `010110`, two motors) closed from 100 → 96, stopped mid-travel at 52, reopened to 100; owner confirmed both motors moved together. Irismo: `RoomD SH` (group `010112`, `40FCFC` behind the 1811129 bridge) closed and reopened on command, verified by eye since it reports no position by design. | 2026-07-29 | Live service calls plus owner observation |
| **HA-06** | **`via_device` referenced a device that did not exist.** Motor devices declare the gateway as parent, but the gateway was only created implicitly by the group entities, and motors were added first. HA warned and said it would stop working in a later release. Fixed by registering the gateway explicitly during setup, before any entity is added, and by adding groups ahead of motors. | 2026-07-29 | Found in `get_error_log` during live validation; fixed in v0.1.3. **Confirmed gone after installing v0.1.3 and rebooting: 0 occurrences of `ha_somfy`, `via_device` or `non existing` across the full 1003-line log.** The log covers a fresh boot and still carries `rinnai`'s setup-time `helpers/frame` warning 12 times — the same warning type that previously shared a line with ours — so the absence is real, not an empty buffer |
| HACS-01 | HACS-native layout | 2026-07-29 | CI: HACS action reports **all 9 checks passed** (needed repo topics + brand assets) |
| HACS-02 | CI: hassfest + HACS + ruff + pytest | 2026-07-29 | All four jobs green on `main`; **123 tests passed** |
| HACS-04 | `requirements: []` maintained | 2026-07-29 | CI: hassfest passes with the client vendored and no external requirements |

---

## Maintenance process

1. **Review this file at the start of any work session**, and again before closing one out.
2. **Add** newly discovered items immediately, with a fresh stable ID, priority, and a concrete
   *Done when*. Never reuse an ID.
3. **Complete:** verify with real evidence first (per the `verify` discipline — fresh command,
   test, or MCP output, not assumption), then move the row to **Completed** with the date.
4. **Delete** items that are no longer relevant, and note the deletion in the revision log.
5. **Commit each revision** and push to `origin/main`.
6. Items large enough to need design work graduate to the AI DevKit lifecycle
   (`/new-requirement` → `docs/ai/<phase>/feature-<name>.md`) and link back to their ID here.

## Revision log

| Date | Change |
|------|--------|
| 2026-07-29 | Created. Seeded with 30 items from the project plan and the live gateway reconnaissance (ports open, 25 group names read, `somfy_devices.json` 403, 1811129 confirmed on all 9 Irismo). |
| 2026-07-30 | **WORK-02 deleted** (rotate the gateway password), at the owner's decision. Both credentials are confirmed absent from git and live only in the gitignored `scripts/secrets.local.json` and the HA config entry, which is where a config-entry password belongs. The device is LAN-only, so the threat model requires an attacker already inside the network and the session store. Rotating would have broken the probe scripts and the HA entry for no meaningful gain. **The standing rule is unchanged: credentials are never committed.** |
| 2026-07-29 | **PERF-03, HW-04, PROTO-07 and PROTO-09 all closed.** PERF-03 verified live by the owner. HW-04 added as a deliberately narrow check — it warns only when a name matches *another* existing group, so the current fleet produces zero warnings while the real `136E33` case would still fire. PROTO-09: the `sdn.` prefix is optional, both forms return identical payloads. PROTO-07: closed as not worth pursuing, since `somfy_devices.json` is 403 even with basic auth and the per-node endpoint returns more anyway. Gateway device now carries firmware and serial from `about.json`. |
| 2026-07-29 | **Brand icon mechanism corrected.** The `custom_components/ha_somfy/brand/` folder was already the right answer: since HA 2026.3 custom integrations serve their own brand images locally and `home-assistant/brands` no longer accepts them (PR #10871 closed on that basis). The grey placeholder in the HACS store list is the CDN fallback for a not-yet-installed integration, not a defect. Added WORK-05/06; released v0.1.1 so the install picks up the redrawn icon. |
| 2026-07-29 | **`false` position explained.** Owner confirmed `077537` "RoomB B/O 3" is physically disconnected pending repair and was deliberately removed from its group. That makes both `false`-replying motors known-faulty hardware, 2 for 2 against 38 healthy motors returning numbers — so `{"result": false}` signals a motor-side fault, not the "unset limits" originally guessed. Q2 in the protocol findings is resolved; MIGRATE-05 downgraded to parked (no action needed). |
| 2026-07-29 | **OPEN-01 resolved.** New entities keep their own IDs; references migrate to them. Collision check showed no `_2` suffixes will occur, so nothing needs renaming. Added MIGRATE-01..05 and `entity-migration-map.md` with the full 24-row mapping. Two findings from building it: the four all-Irismo groups currently advertise a position capability they have never had, and `077537` belongs to no group so `RoomB B/O` reaches only 2 of 3 motors. |
| 2026-07-29 | **Correction:** the 24 `cover.*` entities are Homebridge-bridged and live, not orphans. WORK-01 rewritten from "purge them" to "preserve them". Added OPEN-01: freeing the old entity IDs does not by itself make the new group entities adopt them, since IDs come from the gateway's group names. Phase 6 is on hold at the owner's request. |
| 2026-07-29 | **Phases 2-5 complete, CI fully green** (123 tests, hassfest, HACS 9/9, ruff). Two failures only CI could catch: pytest-socket (pulled in by the HA harness) blocked the client tests' loopback socket, and HACS required repository topics plus brand assets. Remaining before release: PROTO-08 position polarity and WORK-01 orphan purge, both needing live hardware. |
| 2026-07-29 | **Phase 1 gate passed.** PROTO-01..06 completed. Added PROTO-08/09, CAP-04/05/06, GROUP-03, HW-01/02/03, PERF-04. Key correction: the classifier must match **`SDN Module`**, not `irismo` — the planned substring list would have matched none of the 9 Irismo. Second correction: the bus is fast, not slow, so the cautious polling assumption in the plan was unnecessary. |
