# UAI+ protocol — Phase 1 findings

**Status:** gate passed · **Captured:** 2026-07-29 · **Gateway:** Somfy Connect UAI+, HW 04.04 / FW 02.03.11
**Evidence:** `tests/fixtures/wire_samples.json`, `tests/fixtures/bus_inventory.json`

Everything below was measured against the live bus with a query-only probe
(`scripts/probe_uai.py`), not inferred from prior art. Where this contradicts the planning
assumptions, the measurement wins.

---

## 1. The headline: Irismo reports `"SDN Module"`

`sdn.status.info` returns `{"name": ..., "type": ...}`. Across all 49 nodes, exactly three type
strings exist:

| `type` string | Count | Position? | Hardware |
|---|---|---|---|
| `Sonesse 50DC` | 28 | yes | Sonesse 50 DC tubular |
| `Sonesse 30` | 12 | yes | Sonesse 30 tubular |
| `SDN Module` | **9** | **no** | **Irismo via 1811129 SDN bridge** |

28 + 12 = 40 Sonesse and 9 Irismo — matching the known fleet exactly.

**The word "Irismo" never appears on the wire.** The gateway describes the *bridge module*, not the
motor behind it. Any classifier keyed on `"irismo"` — the obvious guess, and what the planning
document proposed — would match **zero** of the nine. This is the single most important finding of
Phase 1, and it invalidates the substring list drafted during planning.

All 9 refuse position identically:

```
--> {"method":"sdn.status.position","params":[{"targetID":"40FD76"}],"id":1046}
<-- {"error":-32600,"id":1046}
```

Note `error` is a **bare integer**, not a JSON-RPC error object, and there is **no `result` key**.

### Node ID ranges correlate with type

`136xxx` → Sonesse 50DC · `077xxx`/`076xxx` → Sonesse 30 · `40FCxx`/`40FDxx` → SDN Module.

Clean on this bus, but it is an artefact of one site's commissioning order. **Use it only as a
diagnostic cross-check, never as the classifier.**

## 2. `params` is a list of single-key dicts (PROTO-03, settled)

```json
{"method":"sdn.status.info","params":[{"targetID":"136EA5"}],"id":1002}
```

Confirmed by runtime shape detection. The bare-dict form used by `peter-dolkens/somfy-uai` is wrong.

## 3. A position-capable motor can answer `false`

```
<-- {"result":false,"id":1106}      # 07753E "RoomB SH 2", type Sonesse 30
```

`false` means *position currently unknown*, *not* *this motor has no position*. Persistent across 3
consecutive passes, while sibling `07752B` on the same run returned a valid number — so it is a
property of that motor, not of the bus.

### What `false` actually indicates: a physical-layer fault

Exactly **two** of the 49 nodes reply `false`, and the owner confirmed both are physically faulty:

| Node | Name | Status per owner | Confirmed |
|---|---|---|---|
| `077537` | RoomB B/O 3 | **Physically disconnected**, awaiting repair; removed from its group | volunteered unprompted |
| `07753E` | RoomB SH 2 | **Physically faulty / disconnected**, same class of fault | confirmed on direct question |

All 38 healthy position-capable motors return a number. The correlation is 2 for 2 in both
directions, which is strong evidence that **`{"result": false}` means the SDN electronics are
answering but the motor itself is not reporting** — a disconnected or failed motor, rather than the
"limits never set" explanation originally guessed.

> **On the strength of this claim.** A first version of this section asserted both motors were
> faulty on the basis of the owner ticking a "known issue, already aware" option — which
> established awareness, not a cause. The physical fault on `07753E` was confirmed separately
> afterwards. The conclusion stands, but the sample is two motors on one bus: treat `false` as a
> strong hint to inspect the motor, not as proof of a fault.

That makes `false` a genuinely useful diagnostic: a Sonesse persistently replying `false` is worth
physically inspecting. It also confirms the design decision — capability must come from the type
string, because a faulty motor is still a *position-capable* motor and must not be silently
reclassified as an Irismo.

> **Trap:** `bool` subclasses `int` in Python, so `isinstance(False, int)` is `True`. A naive
> numeric check reads this as position 0. The probe had exactly this bug and reported 40 positional
> nodes instead of 38. Any position parsing must reject `bool` explicitly before the numeric check.

**Design consequence:** capability comes from the **type string**, and a `false` reading marks the
position temporarily unknown. A Sonesse must never be demoted to non-positional because one poll
returned `false` — that would make the entity's feature set flap.

## 4. Group addressing (PROTO-04, settled)

```
groupID = "0101" + f"{index:02X}"      # index = 1-based key in GET /somfy_groups.json
```

Verified against all 24 groups that returned members — e.g. `010106` → 6 → `RoomG B/O`,
`010119` → 25 → `RoomK SH`. Group 1 (`ALL`) returns no membership; it behaves as a broadcast
rather than a stored group, which is why 24 of 25 appear in `sdn.group.get` replies.

`somfy_controls.json` shows `ALL` as `1.1.0`, which disagrees with the `0101 + index` formula by
one. Membership data is authoritative; treat the controls page as a UI artefact.

## 5. The bus is fast, and the planning assumption was wrong

**149 requests in 5.0 s total — mean 0.03 s, max 0.53 s. Zero retries needed across all 49 nodes.**

Planning assumed "the gateway is known to be slow to answer bulk queries" and prescribed cautious
sequential polling. That is not what the hardware does. Polling all 40 positional motors costs
roughly **1.2 s**, which makes a 60 s coordinator interval comfortable and a faster
during-movement poll entirely affordable.

Helped by there being **no Somfy keypad on this bus** — the main documented source of SDN contention.

## 6. Reliability: rare single-node dropout

Six discovery passes returned 49 nodes. One pass omitted `077537` (`RoomB B/O 3`), which was then
present in 4 of 4 follow-up pings. Somfy's own integration guide warns that on a busy bus "there is
no guarantee that replies from all devices will be received."

**Design consequence:** discovery is a *union over time*, not a snapshot. Never remove an entity or
mark it unavailable because a node missed a single pass. Persist the known node set and require
several consecutive misses before considering a node gone.

## 7. Wire quirks

- Auth prompts (`User:`, `Password:`) are **not newline-terminated** — read until substring, not until newline.
- The success banner is `Connected:\n\x00` — carries a trailing **NUL byte**.
- Reply whitespace is inconsistent: `{ "result" : { "name" : ...` vs `{"result":["01010A"],...}`. Never depend on formatting.
- Zero stray/push notifications observed in 149 requests, despite `local_push` claims in prior art. **`local_polling` is the honest `iot_class`.**

## 8. Open questions

| # | Question | Why it matters | How to settle |
|---|---|---|---|
| Q1 | Does position 0 mean open or closed? | Inverts the whole cover UI. Somfy convention is 0=open/100=closed, opposite of HA's. Observed values are only ever 0 or 100, so the data cannot disambiguate. | Phase 6: move one motor and observe. **Do not assume.** |
| ~~Q2~~ | ~~Is `RoomB SH 2` faulty, or just missing limits?~~ | **Resolved 2026-07-29.** Both `false`-replying motors are physically faulty per the owner. `false` indicates a motor-side fault, not a configuration gap. See §3. | — |
| Q3 | Do the two `RoomA B/O 2` nodes (`136E33`, `136E3F`) share a name intentionally? | Duplicate friendly names collide when generating entity IDs. | Ask; otherwise disambiguate by node ID. |

## 9. Consequences for the capability classifier

Replacing the design drafted during planning:

1. **Primary signal — the `type` string, matched case-insensitively:**
   - contains `sonesse`, `glydea`, `lsu`, `50dc`, `50ac` → **positional**
   - equals/contains `sdn module` → **non-positional** (this is Irismo)
2. **Do not** match on `irismo` alone — it never appears. Keep it only as an additional alias in
   case other firmware reports it.
3. **Unknown type → probe** `sdn.status.position` once: a numeric reply means positional; `error`
   or a missing `result` means non-positional. `false` is *inconclusive* and must be retried later
   rather than treated as a capability verdict.
4. **Reject `bool` before any numeric check.**
5. Position-capable entities get `SET_POSITION`; non-positional get `OPEN|CLOSE|STOP` plus
   `assumed_state = True`.
