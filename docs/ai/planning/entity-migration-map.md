# Entity migration — HA Somfy takes over the Homebridge entity IDs

**Plan changed 2026-07-30.** The earlier decision (OPEN-01) was to let HA Somfy keep its own
`cover.somfy_uai_*` IDs and rewrite every reference to them. The owner has chosen the opposite and
better end state: **HA Somfy adopts the existing Homebridge entity IDs**, and the Homebridge
entities move aside to `*_2`.

The payoff is large. Every reference in every dashboard, automation, script and scene is by
`entity_id`, so once HA Somfy holds the old ID, **those references resolve to it with no edits at
all**. What was going to be a 68-dashboard rewrite becomes a targeted audit.

## Who does what

Renaming an entity ID, assigning an area and moving an entity between devices are **entity/device
registry** operations. The Home Assistant MCP tool set covers states, services, dashboards,
automations, scripts, scenes, helpers and config files — there is no registry tool and no raw
WebSocket passthrough. So:

| Step | Owner | Status |
|---|---|---|
| 1. One device per group | code | **done** — v0.4.0 |
| 4. Move Homebridge entities aside to `*_2` | owner, in the UI | **done** — 24/24 |
| 2. Rename HA Somfy entities to the Homebridge IDs | owner, in the UI | **done** — 24/24 |
| 3. Assign rooms | owner, in the UI | **done** — 24/24, 0 unassigned |
| 5. Fix what entity_id inheritance does not cover | code/MCP | **done** — MIGRATE-09, 65 refs in 12 automations |
| 6. Retire the Homebridge entities | owner, in the UI | **done** — after testing, 24/24 deleted |

Listed in execution order, which is not the order they were requested in: 4 has to precede 2.

Editing `.storage/core.entity_registry` directly was considered and rejected: Home Assistant holds
that file in memory and rewrites it, so it would require stopping HA — registry surgery on a house
running ~48 wall panels is not worth saving some clicking.

## Two things that will silently ruin this

**1. The order is 4 → 2, not 2 → 4.** `cover.roomi_drapes` is occupied. HA Somfy cannot take
that ID until Homebridge releases it. Do one row at a time: move Homebridge aside, then rename HA
Somfy into the freed ID.

**2. Decline "update all references" on the Homebridge rename.** Home Assistant offers to rewrite
every reference when an entity ID changes. Accepting it on the `*_2` renames would point all 68
dashboards at `*_2` — following Homebridge instead of letting HA Somfy inherit them, which is
exactly backwards. Accept it on the second rename of each pair if offered; by then it is a no-op.

## The table

Work one row at a time, left to right.

| # | Room | ① Homebridge → `_2` | ② HA Somfy → takes the freed ID | Gateway group |
|---|---|---|---|---|
| 1 | RoomA | `cover.rooma_bed_blackouts` | `cover.somfy_uai_rooma_b_o` | RoomA B/O |
| 2 | RoomA | `cover.rooma_bed_shades` | `cover.somfy_uai_rooma_sh` | RoomA SH |
| 3 | RoomB | `cover.roomb_blackouts` | `cover.somfy_uai_roomb_b_o` | RoomB B/O ⚠️ 2 of 3 |
| 4 | RoomB | `cover.roomb_shades` | `cover.somfy_uai_roomb_sh` | RoomB SH |
| 5 | RoomG Living | `cover.roomg_living_blackouts` | `cover.somfy_uai_roomg_b_o` | RoomG B/O |
| 6 | RoomG Living | `cover.roomg_living_drapes` | `cover.somfy_uai_roomg_sh` | RoomG SH **(Irismo)** |
| 7 | RoomH | `cover.roomh_shades` | `cover.somfy_uai_roomh_sh` | RoomH SH |
| 8 | RoomI | `cover.roomi_blackouts` | `cover.somfy_uai_roomi_b_o` | RoomI B/O **(Irismo)** |
| 9 | RoomI | `cover.roomi_drapes` | `cover.somfy_uai_roomi_sh` | RoomI SH **(Irismo)** |
| 10 | RoomJ † | `cover.roomj_blackouts` | `cover.somfy_uai_roomj_b_o` | RoomJ B/O |
| 11 | RoomJ † | `cover.roomj_shades` | `cover.somfy_uai_roomj_sh` | RoomJ SH |
| 12 | RoomL | `cover.rooml_bed_blackouts` | `cover.somfy_uai_rooml_b_o` | RoomL B/O |
| 13 | RoomL | `cover.rooml_bed_shades` | `cover.somfy_uai_rooml_sh` | RoomL SH |
| 14 | RoomM | `cover.roomm_blackouts` | `cover.somfy_uai_roomm_b_o` | RoomM B/O |
| 15 | RoomM | `cover.roomm_shades` | `cover.somfy_uai_roomm_sh` | RoomM SH |
| 16 | RoomC | `cover.roomc_blackout` | `cover.somfy_uai_roomc_b_o` | RoomC B/O |
| 17 | RoomD Living † | `cover.roomd_hallway_drapes` | `cover.somfy_uai_roomd_sh` | RoomD SH **(Irismo)** |
| 18 | RoomE Bath | `cover.roome_bath_shade` | `cover.somfy_uai_roome_bath_sh` | RoomE Bath SH |
| 19 | RoomE Bed | `cover.roome_bed_blackout` | `cover.somfy_uai_roome_bed_b_o` | RoomE Bed B/O |
| 20 | RoomE Bed | `cover.roome_bed_shade` | `cover.somfy_uai_roome_bed_sh` | RoomE Bed SH |
| 21 | RoomF Bath | `cover.roomf_bath_shade` | `cover.somfy_uai_roomf_bath_sh` | RoomF Bath SH |
| 22 | RoomF Bed | `cover.roomf_bed_blackout` | `cover.somfy_uai_roomf_bed_b_o` | RoomF Bed B/O |
| 23 | RoomF Bed | `cover.roomf_bed_shade` | `cover.somfy_uai_roomf_bed_sh` | RoomF Bed SH |
| 24 | RoomK | `cover.roomk_shade` | `cover.somfy_uai_roomk_sh` | RoomK SH |

Rooms are where the owner assigned them, verified live on 2026-07-30 — all 24 devices carry an
area and none is left unassigned. As of v0.4.0 each group is its own device, so the device carries
the area and the entity follows.

† **Three deliberately differ from where Homebridge had them**, confirmed by the owner. The two
RoomJ groups sat in *RoomN* despite their names, and `RoomD Hallway Drapes` sat
in *1F Hallway* though the drape is in the roomd living room. These are corrections of
long-standing Homebridge mis-assignments, not migration artifacts — worth recording so nobody
later "fixes" them back by copying the old areas.

## What is left for me afterwards

Entity-ID inheritance covers most of step 5. It does **not** cover:

1. **References by `device_id`.** Found: **65, across 12 automations**, all in device triggers and
   device conditions — none in dashboards or scripts, and there are no scenes. All repointed at the
   new per-group devices. **15 of them also carried an entity *registry ID*** (a UUID) rather than
   a plain entity ID; those survive renames and so still resolved to the Homebridge entity, meaning
   a `device_id`-only fix would have left them watching the wrong blind. Now plain `cover.*` IDs.
2. **`cover.set_cover_position` on the four Irismo groups.** Predicted, but **there are none** —
   all 42 such calls target Sonesse-backed covers. The four Irismo groups were never driven by
   position, so nothing needed converting.

Deferring this inventory until after the renames was the right call: nearly every reference fixed
itself, and what remained was 12 automations rather than 68 dashboards.

## Motors

Homebridge exposes **only the 24 group entities**. There is no Homebridge counterpart for the 49
individual motors, so there is nothing to rename them *to*. The owner's preference is to drop the
`Somfy UAI+` prefix from them.

Note that a registry query for the integration returns only the 24 group entities — the motor
entities do not appear, despite being created disabled-by-default. Unresolved, and deliberately
not blocking: nothing references motors, and removing and re-adding the config entry would
re-register everything from scratch.

## Verification after each row

- The renamed HA Somfy entity responds to open/close from a dashboard card.
- Its state still reads correctly (`open`/`closed`, and a position for the 20 Sonesse groups).
- The Homebridge `*_2` entity still exists and is untouched, as a fallback until the whole set is
  proven. **Completed 2026-07-30**: the owner tested every replacement and then deleted all 24.
  Zero unavailable cover entities remain, where there were 24 before this began.

## Provenance

Homebridge entity IDs, friendly names and areas: live entity registry, read 2026-07-30.
HA Somfy entity IDs: `integration_entities('ha_somfy')`, read 2026-07-30 — observed, not predicted.
Group names, IDs and membership: `GET /somfy_groups.json` and `sdn.group.get` across all 49 nodes.
