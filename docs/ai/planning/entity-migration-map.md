# Entity migration map — Homebridge covers → HA Somfy groups

**Purpose:** the 24 existing `cover.*` entities reach Home Assistant through Homebridge. This
integration creates its own group entities with different IDs. This document is the authoritative
old → new mapping used to update dashboards and automations.

**Do not delete the existing entities.** They are live, merely `unavailable` when their bridge is
offline. The decision (2026-07-29) is to let the new entities land with their own IDs and migrate
references to them.

## Status of the "new" column

> ⚠️ **The new entity IDs below are PREDICTED, not observed.** They are derived from Home
> Assistant's slugify applied to the gateway's group names. They must be re-verified against the
> entity registry immediately after the config entry is created, before any dashboard is edited.

**Collision check (verified 2026-07-29):** none of the 24 predicted IDs currently exists in the
entity registry, so Home Assistant will *not* append `_2` suffixes and no existing entity needs
renaming. This was the concern that prompted the earlier purge proposal; it turns out not to apply.

## The mapping

Group ID is `"0101" + hex(index)`; index is the 1-based key in `GET /somfy_groups.json`.

| # | Old entity (Homebridge) | Gateway group | Group ID | New entity (predicted) | Motors | Position? |
|---|---|---|---|---|---|---|
| 1 | `cover.rooma_bed_blackouts` | RoomA B/O | `010102` | `cover.rooma_b_o` | 3 | yes |
| 2 | `cover.rooma_bed_shades` | RoomA SH | `010103` | `cover.rooma_sh` | 2 | yes |
| 3 | `cover.roomb_blackouts` | RoomB B/O | `010104` | `cover.roomb_b_o` | 2 ⚠️ | yes |
| 4 | `cover.roomb_shades` | RoomB SH | `010105` | `cover.roomb_sh` | 4 | yes |
| 5 | `cover.roomg_living_blackouts` | RoomG B/O | `010106` | `cover.roomg_b_o` | 4 | yes |
| 6 | `cover.roomg_living_drapes` | RoomG SH | `010107` | `cover.roomg_sh` | 2 | **NO** |
| 7 | `cover.roomh_shades` | RoomH SH | `010108` | `cover.roomh_sh` | 2 | yes |
| 8 | `cover.roomi_blackouts` | RoomI B/O | `010109` | `cover.roomi_b_o` | 3 | **NO** |
| 9 | `cover.roomi_drapes` | RoomI SH | `01010A` | `cover.roomi_sh` | 3 | **NO** |
| 10 | `cover.roomj_blackouts` | RoomJ B/O | `01010B` | `cover.roomj_b_o` | 2 | yes |
| 11 | `cover.roomj_shades` | RoomJ SH | `01010C` | `cover.roomj_sh` | 2 | yes |
| 12 | `cover.rooml_bed_blackouts` | RoomL B/O | `01010D` | `cover.rooml_b_o` | 3 | yes |
| 13 | `cover.rooml_bed_shades` | RoomL SH | `01010E` | `cover.rooml_sh` | 3 | yes |
| 14 | `cover.roomm_blackouts` | RoomM B/O | `01010F` | `cover.roomm_b_o` | 2 | yes |
| 15 | `cover.roomm_shades` | RoomM SH | `010110` | `cover.roomm_sh` | 2 | yes |
| 16 | `cover.roomc_blackout` | RoomC B/O | `010111` | `cover.roomc_b_o` | 1 | yes |
| 17 | `cover.roomd_hallway_drapes` | RoomD SH | `010112` | `cover.roomd_sh` | 1 | **NO** |
| 18 | `cover.roome_bath_shade` | RoomE Bath SH | `010113` | `cover.roome_bath_sh` | 1 | yes |
| 19 | `cover.roome_bed_blackout` | RoomE Bed B/O | `010114` | `cover.roome_bed_b_o` | 1 | yes |
| 20 | `cover.roome_bed_shade` | RoomE Bed SH | `010115` | `cover.roome_bed_sh` | 1 | yes |
| 21 | `cover.roomf_bath_shade` | RoomF Bath SH | `010116` | `cover.roomf_bath_sh` | 1 | yes |
| 22 | `cover.roomf_bed_blackout` | RoomF Bed B/O | `010117` | `cover.roomf_bed_b_o` | 1 | yes |
| 23 | `cover.roomf_bed_shade` | RoomF Bed SH | `010118` | `cover.roomf_bed_sh` | 1 | yes |
| 24 | `cover.roomk_shade` | RoomK SH | `010119` | `cover.roomk_sh` | 1 | yes |

Group 1 (`ALL`, `010101`) is a broadcast with no stored membership and is deliberately not exposed.

## Two behaviour changes to expect

### 1. Four entities lose their position slider — correctly

Rows **6, 8, 9, 17** are the all-Irismo groups. Every member is an Irismo motor behind a Somfy
1811129 SDN bridge, which physically cannot report or accept a position.

Today those four report `supported_features: 15` through Homebridge, i.e. they *claim*
`SET_POSITION`. That claim has always been false. After migration they will report `11`
(open/close/stop) and carry `assumed_state`.

**Action:** any dashboard card or automation calling `cover.set_cover_position` on these four is
currently a no-op dressed up as a control. Those calls need replacing with
`cover.open_cover` / `cover.close_cover`. Search for:

- `cover.roomg_living_drapes`
- `cover.roomi_blackouts`
- `cover.roomi_drapes`
- `cover.roomd_hallway_drapes`

### 2. One motor is out of service by design

`077537` — **"RoomB B/O 3"**, a Sonesse 30 — belongs to **no group**, so `cover.roomb_b_o` drives
**2 of 3** RoomB blackout motors (`077526`, `07752C`).

**This is intentional and needs no action.** The owner physically disconnected it pending repair
and removed it from the group. It will be added back once fixed.

Everything the probe saw is consistent with that: it replies `false` to position queries, and it
missed one discovery pass. Its SDN electronics still answer, which is why it appears in discovery
at all.

**When the motor is repaired:** add it back to `RoomB B/O` in the UAI+ web UI, then reload the
integration. Discovery picks up the new membership and `cover.roomb_b_o` covers all three. No code
change required.

Until then it exists only as a motor entity, which is disabled by default — so it will not appear
in the UI or generate any traffic.

## Migration procedure

1. **Create the config entry** and let entities land with their own IDs.
2. **Re-verify the new column** against the live entity registry. Do not skip this — the IDs above
   are predicted from a slugify rule, not observed.
3. **Inventory references.** Fetch each of the 68 dashboards via `get_dashboard_config` and each
   automation and script config, and record every occurrence of the 24 old IDs. Produce a
   per-dashboard list before editing anything.
4. **Back up** with `backup_config_files` / dashboard configs saved locally.
5. **Rewrite references** old → new, one dashboard at a time, verifying each before moving on.
   Treat the four Irismo entities specially per the note above.
6. **Leave the Homebridge entities in place** until the new entities are proven, so there is a
   working fallback. Retire them only afterwards, and only if you want to.

## Provenance

Old entity IDs and friendly names: live HA entity registry, read 2026-07-29.
Group names, IDs and membership: `GET /somfy_groups.json` and `sdn.group.get` across all 49 nodes,
captured in `tests/fixtures/bus_inventory.json`.
