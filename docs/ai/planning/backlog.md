# HA Somfy — Pending Items

Living backlog for the HA Somfy integration. **Continuously revised**: items are added as they
surface, marked complete when verified, and deleted when no longer relevant.

- **Status:** `open` · `in-progress` · `blocked` · `parked` · `done` (move to [Completed](#completed))
- **Priority:** `H` high · `M` medium · `L` low
- **IDs are stable** — never renumber or reuse an ID, even after deletion.

> ## Standing constraint — WORK-01
>
> **DO NOT DELETE the 24 existing `cover.*` entities.** They are **not** orphans: they are live
> entities bridged into HA via **Homebridge**, merely `unavailable` at the time of inspection. An
> earlier reading of this backlog wrongly identified them as leftovers from a failed integration
> and recommended purging them; deleting them would have destroyed working configuration.
> `restored: true` plus a 1:1 name match to the 24 groups is **not** evidence an entity is dead —
> here it meant the same groups were already reaching HA by another route.
>
> This is a rule, not a task. It has no completion state and must never be moved to Completed.

---

## 1. Entity migration — the active workstream

The integration works; what remains is pointing the existing Home Assistant configuration at the
new entities. Mapping lives in [`entity-migration-map.md`](entity-migration-map.md), verified
against the live registry (MIGRATE-01).

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| MIGRATE-02 | **Inventory every reference** to the 24 old entity IDs across 68 dashboards, plus automations, scripts and scenes. Produce a per-dashboard list before changing anything. | H | open | Complete reference inventory produced and reviewed |
| MIGRATE-03 | **Rewrite references old → new**, one dashboard at a time with verification between each, after taking backups. Leave the Homebridge entities in place as a fallback until the new ones are proven. | H | blocked by MIGRATE-02 | All references migrated and each dashboard verified |
| MIGRATE-04 | **Fix the four Irismo entities' position calls.** `cover.roomg_living_drapes`, `cover.roomi_blackouts`, `cover.roomi_drapes` and `cover.roomd_hallway_drapes` currently claim `supported_features: 15` via Homebridge, including `SET_POSITION` — a claim that has always been false, since Irismo has no position feedback. After migration they correctly report `11`. Any `cover.set_cover_position` call on them is a no-op today and must become open/close. | H | blocked by MIGRATE-02 | No `set_cover_position` calls remain against the four Irismo groups |
| AREA-01 | **Reassign the 24 group entities to their real rooms.** They inherit the gateway device's area (`it_equipment`). Cosmetic, and better done after the dashboard migration so entity IDs are settled first. | L | blocked by MIGRATE-03 | Each group entity sits in its own room's area |

## 2. Deferred and optional

Nothing here blocks use of the integration.

| ID | Item | Pri | Status | Done when |
|----|------|-----|--------|-----------|
| CAP-02 | **Per-motor capability override in the options flow** — force-position / force-no-position, as the manual escape hatch when detection is wrong. The options flow today exposes the poll interval only (`SomfyOptionsFlow.async_step_init`). Speculative: detection has been correct on all 49 nodes, so this stays unbuilt until something is actually misdetected. | L | open | Override settable per motor and respected by the entity |
| TEST-01 | **No test covers `extra_state_attributes` on either entity class.** The motor `groups` attribute (GROUP-02) and the group `members`/`member_count` attributes are implemented and correct, but nothing would catch their removal or a change that made them churn — and churn here fans out to ~48 panels. Every other behavioural claim in this file is backed by a named test; these two are not. | M | open | A test asserts both attribute sets and that they are static |
| WORK-03 | **Author a `somfy-sdn` skill** from Phase 1 findings. No skill exists anywhere for Somfy SDN, HACS/custom-component development, or telnet — verified across 74 registries / 3604 skills. | L | open | Skill written and usable |
| WORK-04 | **There is no `post-commit` auto-push hook.** `CLAUDE.md` requires a push after every commit; that has been happening by hand, not automatically. `.git/hooks/post-commit` does not exist, and `.git/hooks/` cannot be version-controlled, so a fresh clone would have nothing either. Either script it into the repo with a documented install step, or drop the requirement and keep pushing manually. | L | open | Either a tracked hook with an install step, or `CLAUDE.md` updated to say pushes are manual |
| HW-01 | **Two motors reply `false` to position, and both are confirmed physically faulty** — `07753E` "RoomB SH 2" and `077537` "RoomB B/O 3", both disconnected/faulty pending repair. All 38 healthy positional motors return a number, so the correlation is 2 for 2. **`false` therefore signals a motor-side fault, not a configuration gap** — a useful diagnostic, and confirmation that capability must come from the type string so a faulty Sonesse is never silently reclassified as an Irismo. No action expected; the integration shows position as unknown without demoting capability. | L | parked | Awaiting the owner's physical repair; software side already covered by CAP-06 |
| MIGRATE-05 | **`077537` "RoomB B/O 3" is out of service by design — no action needed.** Owner physically disconnected it pending repair and removed it from `RoomB B/O`, so that group correctly has 2 members and `cover.roomb_b_o` drives 2 of 3. When repaired: add it back to the group in the UAI+ web UI and reload the integration; discovery picks up the membership with no code change. Until then it exists only as a disabled-by-default motor entity, generating no traffic. | L | parked | Motor repaired, re-added to the group, and discovery reflects 3 members |
| WORK-05 | **Icon works in Home Assistant. The HACS store list cannot be fixed from this repo.** Confirmed on the live system after installing v0.1.1: the icon renders in *Add Integration*, proving `brand/icon.png` and the local API work. It does **not** render in the HACS store list. Cause: HACS ships its own bundled frontend pinned to an **older** `homeassistant-frontend` submodule (`3ffbd43`) whose `brandsUrl()` builds a CDN URL directly — `https://brands.home-assistant.io/_/{domain}/dark_icon.png` — with no local-API path and no token. That URL returns the grey placeholder for `ha_somfy`, verified. Current HA frontend instead returns `/api/brands/integration/{domain}/…`, which is why HA's own UI works. **No custom integration created after the brands repo closed to them can have a HACS store-list icon** until HACS updates its vendored frontend. Cosmetic only, and confined to that one list. | L | parked | HACS updates its bundled frontend; nothing actionable here |

## Completed

| ID | Item | Done | Evidence |
|----|------|------|----------|
| PROTO-01 | Built `scripts/probe_uai.py`, query-only with an enforced allowlist | 2026-07-29 | Ran clean against all 49 nodes; `tests/test_probe_safety.py` proves 13 mutating/unknown methods are refused and 4 read-only ones permitted |
| PROTO-02 | **Irismo reports `type: "SDN Module"`** — all 9, identically. The string `irismo` never appears; the gateway names the 1811129 bridge, not the motor. All 9 refuse position with `{"error":-32600}` | 2026-07-29 | `tests/fixtures/bus_inventory.json` — histogram `Sonesse 50DC=28, Sonesse 30=12, SDN Module=9` |
| PROTO-03 | `params` is a **list of single-key dicts**, not a bare dict | 2026-07-29 | Runtime shape detection returned `list`; 149 successful requests |
| PROTO-04 | Group address = `"0101" + f"{index:02X}"`, index 1-based from `somfy_groups.json`. Group 1 `ALL` is a broadcast with no stored membership | 2026-07-29 | All 24 member-bearing groups matched by name, e.g. `010106`→`RoomG B/O`, `010119`→`RoomK SH` |
| PROTO-05 | Bus is fast and reliable: 149 requests in 5.0 s, mean 0.03 s, **zero retries**. One transient single-node dropout observed → HW-02 | 2026-07-29 | `timings` in probe output; 6 discovery passes |
| PROTO-06 | Sanitised fixtures committed; raw captures gitignored | 2026-07-29 | `tests/fixtures/*.json` committed; credential scan across all committable files came back clean |
| PROTO-08 | **Position polarity confirmed correct.** `GATEWAY_POSITION_IS_INVERTED = True` stands; Somfy 0 = open, HA 0 = closed. Settled with **zero movement**. | 2026-07-29 | Live entities read closed for all four bathroom/toilet shades and both guest bed blackouts, open for everything else; owner confirmed that matches the physical blinds |
| PROTO-09 | **The `sdn.` prefix is optional.** `status.info`, `status.position` and `group.get` return payloads identical to their prefixed forms. Usable as a fallback; no reason to switch. | 2026-07-29 | `scripts/probe_open_questions.py`, all three pairs identical |
| PROTO-07 | **Answered — the endpoints do unlock, but are not worth adopting.** Owner spotted that `pilot.htm` has its own password. Auth is `GET /password.cgi?VERIFY=<web password>`, a separate credential from telnet, and it sets **no cookie** — the session is IP-bound. Afterwards `somfy_devices.json` returns all 49 labels in **one** request, including the two nodes the per-node endpoint never served, and `somfy_presets.json` returns 16 slots per node. **All 16 are empty on all 49 nodes**, so there is no preset feature to build. Not adopted: discovery already names all 49 correctly without it, and adopting would add a second credential to the config flow for every user plus IP-bound session handling. | 2026-07-30 | `scripts/probe_web_session.py`; 49 devices, 49 labels, 0 presets |
| CAP-01 | Classifier maps type string → capability, probing unknown types | 2026-07-29 | `tests/test_models.py`; replaying the real 49-node inventory splits exactly 40 positional / 9 non-positional with 0 unknown |
| CAP-03 | **`supported_features` is never hardcoded — the fix this project exists for, verified in CI and on real hardware.** Four all-Irismo groups report `supported_features: 11` with `assumed_state: true`; all twenty Sonesse groups report `15` with real positions. | 2026-07-29 | CI: `test_irismo_does_not_advertise_set_position` and `test_sonesse_does_advertise_set_position`. Live: `batch_get_state` across all 24 group entities |
| CAP-04 | `bool` rejected before any numeric position check | 2026-07-29 | `test_bool_is_never_a_position`; the probe's own version of this bug was found and fixed |
| CAP-05 | Classifier matches `SDN Module`, not `irismo` | 2026-07-29 | `test_sdn_module_is_non_positional`; `irismo` retained only as a defensive alias |
| CAP-06 | A `false` reading leaves capability untouched | 2026-07-29 | `test_the_false_position_node_keeps_its_capability` against real node `07753E` |
| GROUP-01 | Group cover entities, open/close/stop | 2026-07-29 | CI: `test_all_irismo_group_has_no_position_slider`, `test_all_sonesse_group_has_a_position_slider` |
| GROUP-02 | Per-motor group membership exposed as a static entity attribute | 2026-07-30 | `cover.py:206-211` returns `node_id`, `motor_type`, `capability` and `groups`, with an explicit comment that only static values belong there. Untested — see TEST-01 |
| GROUP-03 | Group 1 `ALL` omitted from discovery | 2026-07-29 | `UaiClient.async_get_groups` filters it; `test_discovery_skips_the_all_group` |
| GROUP-04 | Groups inherit least-capable member | 2026-07-29 | CI: `test_mixed_group_falls_back_to_least_capable` |
| PERF-01 | Change-gated state writes | 2026-07-29 | CI: `test_state_is_written_only_when_something_changed` — 3 refreshes, 1 write |
| PERF-02 | Only position-capable motors are polled | 2026-07-29 | `SomfyCoordinator._async_update_data` skips non-positional nodes; the 9 Irismo generate no poll traffic |
| PERF-03 | **A moving cover updates promptly instead of waiting up to 60 s.** `async_follow_movement` polls only the nodes just commanded, every 2 s, dropping each after 3 unchanged reads (~6 s, covering motor start-up), with a 120 s ceiling. Non-positional nodes are filtered out entirely, so the nine Irismo add no traffic; entities stay change-gated, so a no-op poll writes nothing. | 2026-07-29 | 7 coordinator tests in CI, plus owner confirmation on live hardware: "the lag is gone, it updates nicely" |
| PERF-04 | `iot_class` declared `local_polling` | 2026-07-29 | `manifest.json`; zero unsolicited notifications were seen in 149 probe requests |
| HA-01 | Config flow authenticates for real | 2026-07-29 | CI: `test_bad_credentials_are_rejected` |
| HA-02 | Config flow uses auto-discovery | 2026-07-29 | CI: `test_confirm_step_reports_the_capability_split`; no hand-typed motors anywhere |
| HA-03 | Single-argument step handlers | 2026-07-29 | CI: `test_flow_completes_and_creates_an_entry` — the flow reaches CREATE_ENTRY |
| HA-04 | `diagnostics.py` with credentials redacted | 2026-07-29 | `async_get_config_entry_diagnostics` redacts username and password via `TO_REDACT` |
| HA-05 | One device per motor | 2026-07-29 | CI: `test_each_motor_is_its_own_device_showing_its_model` |
| HA-06 | **`via_device` referenced a device that did not exist.** Motor devices declare the gateway as parent, but the gateway was only created implicitly by the group entities, and motors were added first. HA warned and said it would stop working in a later release. Fixed by registering the gateway explicitly during setup, before any entity is added, and by adding groups ahead of motors. | 2026-07-29 | Found in `get_error_log` during live validation; fixed in v0.1.3. **Confirmed gone after installing v0.1.3 and rebooting: 0 occurrences of `ha_somfy`, `via_device` or `non existing` across the full 1003-line log.** The log covers a fresh boot and still carries `rinnai`'s setup-time `helpers/frame` warning 12 times — the same warning type that previously shared a line with ours — so the absence is real, not an empty buffer |
| HW-02 | Transient node dropout tolerated | 2026-07-29 | `SomfyCoordinator.async_discover` requires 3 consecutive misses before dropping a node |
| HW-03 | **Void — there is no duplicate name.** `136E33` is `RoomA SH 2`, not `RoomA B/O 2`; confirmed by the owner's web UI, the gateway's HTTP `LABEL`, and a later telnet read. The 14:04 capture recorded the wrong name while that node's group membership (`010103` = `RoomA SH`) already said otherwise — the contradiction was in the data and went unchecked. Nothing to rename. The uniqueness guard stays as a defensive measure. | 2026-07-29 | §10 of the protocol findings; superseded by the HW-04 guard |
| HW-04 | **Discovery warns when a node's name points at a group it is not in.** Narrow by design: whitespace and case are ignored, so `RoomI SH 1` in `RoomI SH` is silent, and a name resembling no other group, like `RoomD Hall SH` in `RoomD SH`, is silent too. Only a name matching *another existing group* warns — which is exactly the `136E33` case. | 2026-07-29 | `find_name_group_conflicts` + 7 tests, including one asserting the current 49-node fleet produces **zero** warnings |
| NAME-01 | **Names resolved from two sources.** `sdn.status.info` answers a *first* read with a name synthesised from group membership when the gateway has not yet read the device's own label; the query triggers that read and a second call returns the truth. Discovery therefore reads each node twice and prefers the gateway's HTTP `LABEL`. Matters because entity IDs derive from the name and are assigned once. | 2026-07-29 | Verified live: 49 nodes, 0 unnamed, 46 from HTTP and 3 from the second telnet read — including `40FD89`, which HTTP never served |
| OPEN-01 | **New entities land with their own IDs; references get migrated.** No renaming of the Homebridge entities is needed — a collision check confirmed none of the 24 predicted new IDs already exists, so Home Assistant will not append `_2`. | 2026-07-29 | Mapping documented in [`entity-migration-map.md`](entity-migration-map.md) |
| MIGRATE-01 | Entity IDs re-verified against the live registry | 2026-07-29 | All 24 observed as `cover.somfy_uai_*` — HA prefixes the gateway device name, so the predicted `cover.roomb_sh` form was wrong. Map corrected; member counts match the Phase 1 probe exactly |
| LIVE-01 | **Movement verified on real hardware — both paths.** Sonesse: `RoomM SH` (group `010110`, two motors) closed from 100 → 96, stopped mid-travel at 52, reopened to 100; owner confirmed both motors moved together. Irismo: `RoomD SH` (group `010112`, `40FCFC` behind the 1811129 bridge) closed and reopened on command, verified by eye since it reports no position by design. | 2026-07-29 | Live service calls plus owner observation |
| HACS-01 | HACS-native layout | 2026-07-29 | CI: HACS action reports **all 9 checks passed** (needed repo topics + brand assets) |
| HACS-02 | CI: hassfest + HACS + ruff + pytest | 2026-07-29 | All four jobs green on `main`; **140 tests passed** as of `61c36fa` |
| HACS-03 | Tagged semver releases so HACS offers updates | 2026-07-29 | Six releases `v0.1.0`–`v0.1.5`; v0.1.5 installed and running on the live system |
| HACS-04 | `requirements: []` maintained | 2026-07-29 | CI: hassfest passes with the client vendored and no external requirements |
| WORK-06 | Stale `ajguerre1/brands` fork deleted (created for the rejected PR #10871) | 2026-07-29 | `gh api repos/ajguerre1/brands` → **404**; `gh repo list ajguerre1 --fork` returns nothing; `ha-somfy` confirmed intact and not a fork |

---

## Maintenance process

1. **Review this file at the start of any work session**, and again before closing one out.
2. **Add** newly discovered items immediately, with a fresh stable ID, priority, and a concrete
   *Done when*. Never reuse an ID.
3. **Complete:** verify with real evidence first (per the `verify` discipline — fresh command,
   test, or MCP output, not assumption), then **move** the row to **Completed** with the date.
   Moving means *cutting*, not copying — a row must never exist in both places.
4. **Delete** items that are no longer relevant, and note the deletion in the revision log.
5. **Commit each revision** and push to `origin/main`.
6. Items large enough to need design work graduate to the the lifecycle toolkit lifecycle
   (`/new-requirement` → `docs/ai/<phase>/feature-<name>.md`) and link back to their ID here.

## Revision log

| Date | Change |
|------|--------|
| 2026-07-30 | **Full reconciliation — the file had drifted badly.** 20 of the 36 rows above the fold were *also* in Completed: every item closed since Phase 2 had been copied down rather than moved, so the backlog advertised 36 open items when 16 were open and, after inspection, only 11 genuinely are. Fixed by re-deriving status from the repository rather than from the rows. Corrections in the other direction: **GROUP-02** was implemented all along (`cover.py:206-211`) and **HACS-03** shipped six releases ago; both moved to Completed. **HW-03**, **NAME-01** and **OPEN-01** carried status `done` but had never been moved. **CAP-03** appeared twice *inside* Completed and is now one row carrying both its CI and live evidence. **HACS-02** claimed 123 tests; CI actually reports 140. **WORK-04** understated itself — the `post-commit` hook is not merely untracked, it does not exist, so every push so far has been manual. **WORK-01** was never a task and has been promoted to a standing constraint at the top, where it cannot be completed away. Phase-shaped section headings retired, since all five had emptied; what is left is grouped by what it actually is — the migration workstream, and everything deferred. New: **TEST-01**, no test covers `extra_state_attributes` on either entity class. |
| 2026-07-30 | **Parked section removed**, at the owner's decision. PARK-01 was contributing fixes upstream to `peter-dolkens/somfy-uai`, dropped because that repo has one commit, no license, and two unanswered issues — there is nothing to contribute to. PARK-02 was driving raw SDN over RS-485 without the gateway, dropped because the UAI+ works and performs the framing; the protocol details remain in the design doc should it ever be wanted. Neither blocked anything. |
| 2026-07-30 | **WORK-02 deleted** (rotate the gateway password), at the owner's decision. Both credentials are confirmed absent from git and live only in the gitignored `scripts/secrets.local.json` and the HA config entry, which is where a config-entry password belongs. The device is LAN-only, so the threat model requires an attacker already inside the network and the session store. Rotating would have broken the probe scripts and the HA entry for no meaningful gain. **The standing rule is unchanged: credentials are never committed.** |
| 2026-07-29 | **PERF-03, HW-04, PROTO-07 and PROTO-09 all closed.** PERF-03 verified live by the owner. HW-04 added as a deliberately narrow check — it warns only when a name matches *another* existing group, so the current fleet produces zero warnings while the real `136E33` case would still fire. PROTO-09: the `sdn.` prefix is optional, both forms return identical payloads. PROTO-07: closed as not worth pursuing, since `somfy_devices.json` is 403 even with basic auth and the per-node endpoint returns more anyway. Gateway device now carries firmware and serial from `about.json`. |
| 2026-07-29 | **Brand icon mechanism corrected.** The `custom_components/ha_somfy/brand/` folder was already the right answer: since HA 2026.3 custom integrations serve their own brand images locally and `home-assistant/brands` no longer accepts them (PR #10871 closed on that basis). The grey placeholder in the HACS store list is the CDN fallback for a not-yet-installed integration, not a defect. Added WORK-05/06; released v0.1.1 so the install picks up the redrawn icon. |
| 2026-07-29 | **`false` position explained.** Owner confirmed `077537` "RoomB B/O 3" is physically disconnected pending repair and was deliberately removed from its group. That makes both `false`-replying motors known-faulty hardware, 2 for 2 against 38 healthy motors returning numbers — so `{"result": false}` signals a motor-side fault, not the "unset limits" originally guessed. Q2 in the protocol findings is resolved; MIGRATE-05 downgraded to parked (no action needed). |
| 2026-07-29 | **OPEN-01 resolved.** New entities keep their own IDs; references migrate to them. Collision check showed no `_2` suffixes will occur, so nothing needs renaming. Added MIGRATE-01..05 and `entity-migration-map.md` with the full 24-row mapping. Two findings from building it: the four all-Irismo groups currently advertise a position capability they have never had, and `077537` belongs to no group so `RoomB B/O` reaches only 2 of 3 motors. |
| 2026-07-29 | **Correction:** the 24 `cover.*` entities are Homebridge-bridged and live, not orphans. WORK-01 rewritten from "purge them" to "preserve them". Added OPEN-01: freeing the old entity IDs does not by itself make the new group entities adopt them, since IDs come from the gateway's group names. Phase 6 is on hold at the owner's request. |
| 2026-07-29 | **Phases 2-5 complete, CI fully green** (123 tests, hassfest, HACS 9/9, ruff). Two failures only CI could catch: pytest-socket (pulled in by the HA harness) blocked the client tests' loopback socket, and HACS required repository topics plus brand assets. Remaining before release: PROTO-08 position polarity and WORK-01 orphan purge, both needing live hardware. |
| 2026-07-29 | **Phase 1 gate passed.** PROTO-01..06 completed. Added PROTO-08/09, CAP-04/05/06, GROUP-03, HW-01/02/03, PERF-04. Key correction: the classifier must match **`SDN Module`**, not `irismo` — the planned substring list would have matched none of the 9 Irismo. Second correction: the bus is fast, not slow, so the cautious polling assumption in the plan was unnecessary. |
| 2026-07-29 | Created. Seeded with 30 items from the project plan and the live gateway reconnaissance (ports open, 25 group names read, `somfy_devices.json` 403, 1811129 confirmed on all 9 Irismo). |
