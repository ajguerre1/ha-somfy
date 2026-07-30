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
| 2. Rename HA Somfy entities to the Homebridge IDs | owner, in the UI | pending |
| 3. Assign rooms | owner, in the UI | pending |
| 4. Move Homebridge entities aside to `*_2` | owner, in the UI | pending |
| 5. Fix what entity_id inheritance does not cover | code/MCP | pending |

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
| 10 | RoomN | `cover.roomj_blackouts` | `cover.somfy_uai_roomj_b_o` | RoomJ B/O |
| 11 | RoomN | `cover.roomj_shades` | `cover.somfy_uai_roomj_sh` | RoomJ SH |
| 12 | RoomL | `cover.rooml_bed_blackouts` | `cover.somfy_uai_rooml_b_o` | RoomL B/O |
| 13 | RoomL | `cover.rooml_bed_shades` | `cover.somfy_uai_rooml_sh` | RoomL SH |
| 14 | RoomM | `cover.roomm_blackouts` | `cover.somfy_uai_roomm_b_o` | RoomM B/O |
| 15 | RoomM | `cover.roomm_shades` | `cover.somfy_uai_roomm_sh` | RoomM SH |
| 16 | RoomC | `cover.roomc_blackout` | `cover.somfy_uai_roomc_b_o` | RoomC B/O |
| 17 | 1F Hallway | `cover.roomd_hallway_drapes` | `cover.somfy_uai_roomd_sh` | RoomD SH **(Irismo)** |
| 18 | RoomE Bath | `cover.roome_bath_shade` | `cover.somfy_uai_roome_bath_sh` | RoomE Bath SH |
| 19 | RoomE Bed | `cover.roome_bed_blackout` | `cover.somfy_uai_roome_bed_b_o` | RoomE Bed B/O |
| 20 | RoomE Bed | `cover.roome_bed_shade` | `cover.somfy_uai_roome_bed_sh` | RoomE Bed SH |
| 21 | RoomF Bath | `cover.roomf_bath_shade` | `cover.somfy_uai_roomf_bath_sh` | RoomF Bath SH |
| 22 | RoomF Bed | `cover.roomf_bed_blackout` | `cover.somfy_uai_roomf_bed_b_o` | RoomF Bed B/O |
| 23 | RoomF Bed | `cover.roomf_bed_shade` | `cover.somfy_uai_roomf_bed_sh` | RoomF Bed SH |
| 24 | RoomK | `cover.roomk_shade` | `cover.somfy_uai_roomk_sh` | RoomK SH |

Rooms are the areas the Homebridge entities are in today, read from the live registry on
2026-07-30. As of v0.4.0 each group is its own device, so **assign the device to the area** and the
entity follows.

## What is left for me afterwards

Entity-ID inheritance covers most of step 5. It does **not** cover:

1. **References by `device_id`** rather than entity ID — device triggers and actions in
   automations, and some dashboard cards. Those still point at Homebridge devices and need
   rewriting to the new per-group devices.
2. **`cover.set_cover_position` on the four Irismo groups** (rows 6, 8, 9, 17). Those calls are
   no-ops today: Homebridge advertises `supported_features: 15` for them, a claim that has never
   been true. HA Somfy correctly reports `11`, so the calls must become
   `cover.open_cover` / `cover.close_cover`.

Both are cheap to find once the renames are done, and pointless to inventory before — the
inventory would be almost entirely of references that fix themselves.

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
  proven.

## Provenance

Homebridge entity IDs, friendly names and areas: live entity registry, read 2026-07-30.
HA Somfy entity IDs: `integration_entities('ha_somfy')`, read 2026-07-30 — observed, not predicted.
Group names, IDs and membership: `GET /somfy_groups.json` and `sdn.group.get` across all 49 nodes.
