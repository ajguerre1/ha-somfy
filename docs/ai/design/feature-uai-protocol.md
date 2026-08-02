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

## 6b. Method prefix and the HTTP surface

**The `sdn.` prefix is optional** (PROTO-09, settled 2026-07-29). Both spellings return
identical payloads:

| Prefixed | Bare | Result |
|---|---|---|
| `sdn.status.info` | `status.info` | `{"name": "RoomE Bed B/O", "type": "Sonesse 50DC"}` |
| `sdn.status.position` | `status.position` | `100` |
| `sdn.group.get` | `group.get` | `["010114"]` |

Usable as a fallback, though there is no reason to switch. The integration keeps the
prefixed form.

**HTTP endpoints**, all unauthenticated GETs:

| Path | Status | Use |
|---|---|---|
| `about.json` | 200 | Firmware version and serial — populates the gateway device |
| `somfy_groups.json` | 200 | Group names; the only source for them |
| `somfy_device.json?<dotted-node>` | 200 | Per-node `LABEL`, `TYPE`, position, limits |
| `somfy_controls.json` | 200 | Web-UI tiles; not useful |
| `somfy_devices.json` | 403 → **200 after login** | Every node's label in **one** request |
| `somfy_presets.json?<node>` | 403 → **200 after login** | 16 preset slots per node |

### The 403 endpoints unlock via a pilot.htm session

Not HTTP basic auth — that fails. `pilot.htm` authenticates with a plain GET and treats
200 as success:

```
GET /password.cgi?VERIFY=<web password>
```

**No cookie is set**, so the session is keyed to the client IP. The web password is a
*separate* credential from the telnet one.

Afterwards:

- **`somfy_devices.json`** returns all 49 nodes as `{"NODE": "13.6E.A5", "LABEL": "..."}`
  in a single request — including the two nodes whose per-node `somfy_device.json` never
  responded. It carries only NODE and LABEL, plus a `JOG` setting
  (`{"STEP": 50, "TYPE": "pulses"}`); the per-node endpoint remains richer.
- **`somfy_presets.json?<node>`** returns 16 `PERCENT` and 16 `PULSE` slots. **All 16 are
  empty on all 49 nodes of the reference bus**, so presets are not in use and there is no
  `sdn.move.ip` feature worth building against them.

**Not adopted.** Discovery already names all 49 correctly from the unauthenticated
per-node endpoint plus a settled telnet read. Switching would trade ~49 discovery-time
requests for one, at the cost of a second credential in the config flow for every user and
IP-bound session handling. Documented so the option is known, not taken.

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
| ~~Q3~~ | ~~Do `136E33` and `136E3F` share the name `RoomA B/O 2`?~~ | **Resolved 2026-07-29 — there is no duplicate.** `136E33` is `RoomA SH 2`. The 14:04 capture recorded `RoomA B/O 2` for it, but the gateway's HTTP `LABEL` and a later telnet read both say `RoomA SH 2`. See §10. | — |
| Q4 | Can `sdn.status.info` return a stale `name`? | Entity names come from it. If it can go stale, names could be briefly wrong after a rename. | Watch for a repeat; the HTTP `LABEL` is the cross-check. |

## 10. Two sources of truth for a node's name

The gateway exposes a node's label two ways, and on 2026-07-29 they disagreed:

| Source | `136E33` |
|---|---|
| Telnet `sdn.status.info` → `name`, captured 14:04 | `RoomA B/O 2` |
| HTTP `GET /somfy_device.json?13.6E.33` → `LABEL` | `RoomA SH 2` |
| Telnet `sdn.status.info` → `name`, re-read ~2 h later | `RoomA SH 2` |
| Web UI (owner) | `RoomA SH 2` |

### The mechanism: a group-derived placeholder on first read

The owner spotted the pattern: the telnet values looked like *group* names while the
HTTP values looked like *motor* labels. Testing confirmed it.

**`sdn.status.info` answers for a `groupID` as well as a `targetID`** — the same call
serves both, returning `{"name": ...}` with no `type` field for a group:

```
--> {"method":"sdn.status.info","params":[{"groupID":"01010A"}],"id":1001}
<-- {"result":{"name":"RoomI SH"},"id":1001}
```

And on a first read, every one of the 7 SDN Module nodes returned its **group's name
plus its position in that group**:

| Node | First read | Second read | HTTP `LABEL` | Group name |
|---|---|---|---|---|
| `40FD76` | `RoomI SH 1` | `RoomI SH 1` | `RoomI SH 1` | `RoomI SH` |
| `40FD75` | `RoomI SH 3` | `RoomI SH 3` | `RoomI SH 3` | `RoomI SH` |
| `40FCFC` | `RoomD SH` | `RoomD Hall SH` | `RoomD Hall SH` | `RoomD SH` (sole member, no index) |

So **when the gateway has not yet read a node's own label, it answers with a name
synthesised from group membership. The query itself triggers the real read, and
subsequent calls return the true label.** Only Irismo nodes were affected, presumably
because the SDN bridge is slower to yield its label than a Sonesse.

`136E33` does **not** fit this: it returned `RoomA B/O 2` while in the `RoomA SH`
group, so group synthesis would have produced the *correct* answer. That one looks like
a genuinely stale prior label rather than a placeholder. Two mechanisms may be at work;
the available data cannot separate them.

### Why this is load-bearing

Entity IDs derive from the name and are assigned **once**. A placeholder captured at
first discovery becomes a permanently wrong entity ID.

**Resolution used:** read each node's info twice at discovery and prefer the gateway's
HTTP `LABEL` where available. Verified live — 49 nodes, 0 unnamed, 46 from HTTP and 3
from the second telnet read, including one node HTTP never served in any run. Neither
source alone is sufficient.

### The lesson from how this was missed

**Group membership was the signal that caught it.** At 14:04 the same node reported
group `010103` — `RoomA SH` — while its name said `B/O`. That contradiction sat in
the capture and went unnoticed, and a false "duplicate name" finding was built on top
of it. Membership is derived from the motor's own stored group addresses and proved the
more reliable field.

**Practical consequences:**

- The HTTP `LABEL` endpoint is a useful cross-check, and unlike `/somfy_devices.json`
  (403) the per-device `/somfy_device.json?<dotted-node>` form needs no auth.
- A name that disagrees with its group's name is worth flagging rather than trusting.
- Keep the entity-ID uniqueness guard regardless. It is now defensive rather than
  responding to an observed collision, but nothing prevents an installer from
  labelling two motors identically, and a collision would silently drop an entity.

## 11. Irismo open/closed state exists — over HTTP only (IRIS-01)

**Settled 2026-07-30 on live hardware, with one commanded movement.**

Telnet refuses `sdn.status.position` for all 9 SDN Module nodes, and §1 read that as "an Irismo
has no state to report". That was too strong. The gateway *does* hold an open/closed value for
them; it just does not serve it over telnet.

| Source | SDN Module `40FCFC` |
|---|---|
| Telnet `sdn.status.position` | `{"error":-32600}` — refused, all 9 nodes |
| HTTP `somfy_device.json?40.FC.FC` → `POSITION` | **`"1000 (100 %)"`** |

### It is modelled from the last command, not measured

Opening `RoomD SH` via Home Assistant flipped `40FCFC` from `1000 (100 %)` to `0 (0 %)`
**within 2 seconds** — far quicker than the drape can physically travel — while two control
Irismo nodes stayed at `1000`. Closing it returned it to `1000`.

So the 1811129 bridge still has no feedback. What changed is our understanding of the *gateway*:
it records the state it commanded. That makes the value

- **correct** for open/closed, since these blinds are only ever driven by the gateway;
- **never intermediate** — only ever 0 or 1000, so there is no slider to build;
- **assumed**, in exactly the sense `assumed_state` means. It cannot see a blind moved by any
  other means.

### Only the percentage is comparable

The raw number is not one scale:

| Node | Type | Raw | Percent |
|---|---|---|---|
| `40FCFC` | SDN Module | `1000` | 100 % |
| `136EA5` | Sonesse 50DC | `12406` | 100 % |
| `136DAB` | Sonesse 50DC | `18753` | 100 % |

Sonesse raw values are **encoder pulses**, bounded by that motor's `LIMITS DOWN`. SDN Module uses
a fixed 0–1000. **Parse the parenthesised percentage; never the leading number.**

### The endpoint needs a session, and lies occasionally

`somfy_device.json` returns **403** without a `pilot.htm` session (`GET /password.cgi?VERIFY=`),
which is IP-bound and expires.

> **This invalidates a claim in §6b.** That table lists the per-node endpoint as unauthenticated.
> The probes that established it ran from the owner's own workstation, which had a live browser
> session against the web UI — the scripts were riding it without knowing. **Home Assistant is a
> different IP and has never had a session**, so `async_fetch_device_labels` has been returning
> nothing in production and every name has come from the double telnet read. Harmless, because
> the telnet fallback works, but it was invisible.

It is also transiently wrong. A request for one node can return **another node's payload**, or
404. Measured over the 9 Irismo plus 2 Sonesse: 11/11 resolved within 5 attempts, 2 needed a
second. The payload carries its own `NODE` field, so this is detectable — **compare `NODE`
against what was asked for and retry on mismatch.** Attributing one blind's state to another
would be worse than showing none.

### No telnet alternative

Probed `sdn.status.{detail,state,limits,node,all,motor,percent,pulses}` and `system.listmethods`.
All return `-32600` or `-32602` while `sdn.status.position` answers normally for a Sonesse in the
same session. HTTP is the only route.

## 12. Telnet cannot report Irismo state — and one thing it does instead (IRIS-07)

**Settled 2026-07-30.** Other control systems (Control4, Crestron, RTI, Elan, Lutron) integrate
Irismo behind SDN bridges using the telnet credentials alone and display open/closed state, which
is good reason to think a route exists that IRIS-01 missed. Five hypotheses, all tested, all
negative:

| Hypothesis | Result |
|---|---|
| Position needs repeated polling, as `sdn.status.info` does for names | 8 reads per node, `-32600` every time |
| `sdn.status.position` accepts a `groupID`, as `sdn.status.info` does | `-32602` — the method takes no group |
| `sdn.status.info` returns more fields for an SDN Module | Only `{name, type}`, identical in shape to a Sonesse |
| An HTTP read primes the gateway, then telnet answers | Still `-32600` |
| Another read method exists (`status.level/value/get/report/percentage`) | All `-32600` |
| A raw SDN passthrough on another port | Only 23 and 80 are open |
| The gateway *pushes* state when a motor is commanded | No — see below |

The last one was the most promising, because PERF-04's "zero unsolicited notifications" was
measured during a query-only probe with **nothing moving**. Repeating it while commanding a motor
produced 14 unexpected lines — but they were not notifications.

### The gateway broadcasts replies to every telnet session (IRIS-09)

Those 14 lines carried ids **8703-8716**, sequential, on a connection that had sent only
5001-5003. They were replies to *another session's* requests — Home Assistant's poll cycle —
arriving on ours. **The telnet interface is not session-isolated.**

This matters more than the failed hypotheses. A reply echoes neither the method nor the target,
only the id, so a foreign reply whose id matches one of our pending requests is indistinguishable
from our own and would store one motor's position on another. Replies for ids we never issued were
already dropped; the exposure was the exact-collision case, and a fixed base of `1000` made it a
matter of hours, since polling 40 motors a minute sweeps the counter straight through the low range
other clients use. Request ids now start at an unpredictable point in 100,000-900,000.

It also explains the "flaky HTTP" impression: the gateway allows **one web session at a time**, so
a workstation probing it evicts Home Assistant and vice versa. With only Home Assistant using it,
the endpoint is stable.

### Independently confirmed against Control4

The premise for this investigation was that Control4, Crestron, RTI, Elan and Lutron all show
Irismo state over telnet alone. A Control4 CA-10 is connected to this same gateway on its own
telnet credentials, so the claim was directly testable: **move an Irismo from Home Assistant and
see whether Control4 notices.**

It does not. RoomD SH was closed from Home Assistant; Control4 continued to show it open.

That is decisive, because a locally-modelled state *cannot* know about a command it did not
issue. Control4 is tracking what it sent, exactly as the gateway does internally — it is not
reading state from anywhere. A second, independent implementation on the same hardware has the
same blind spot, which turns "I could not find a method" into "there is no method".

**Consequence, and it runs the other way from the original assumption:** this integration's Irismo
state is *better* than Control4's, not worse. Reading the gateway's own record over HTTP means it
picks up movements made by Control4, the web interface, or anything else. Control4's model goes
stale the moment something else moves the blind, and nothing can fix that from either side — the
data simply is not on telnet.

**Conclusion: HTTP remains the only source of Irismo state.** Not for want of looking.

## 13. STOP works on an Irismo, and the gateway models it as 50 % (IRIS-08)

`sdn.move.stop` addressed to an SDN Module returns `{"result":false}` — **identical to
`sdn.move.up` and `sdn.move.down`**, both of which demonstrably work. On this gateway `false` is
the ordinary acknowledgement for a movement command, not a failure, and the client already reads it
as success (`not response.is_error`).

Verified end to end on `40FCFC`: close, stop after 4 s of travel, and the entity settled at

```
state=open  current_position=50  is_closed=False  assumed_state=True  supported_features=11
```

So the gateway models a stopped Irismo at the midpoint, exactly as the owner reported, and the
existing web read plus fast-follow already surfaces it within seconds. **No code change was
required for stop** — it was working before this investigation began.

## 14. Something outside this repo now depends on §11–§13 (2026-07-30)

Nine wall-panel cards render an Irismo's state from a **partial-position band**, not from
`entity.state`:

```js
const p = entity.attributes.current_position;
if (p != null && p > 0 && p < 100) return 'Stopped';
if (entity.state == 'open') return 'Open';
if (entity.state == 'closed') return 'Closed';
```

**The band test must run first.** `CLOSED_POSITION_THRESHOLD` is 2, so a cover at 50 is `open` as
far as Home Assistant is concerned. Ordered the other way, a stopped blind renders "Open" and the
Stopped branch is unreachable — the bug would look like a dead feature rather than a mistake.

**The band is deliberate, not a loose `== 50`.** `SomfyGroupCover.current_cover_position` is
`round(mean(member positions))`, and these cards address groups of 2 and 3 motors. When members
report unevenly — one web read fails, or a member was commanded individually — the average lands on
25/33/67/75. A strict equality test would blank the label at precisely the moment the user wants
feedback. Any value strictly between the endpoints means *not fully at either end*, which for a
device whose only states are open/closed/stopped is exactly "Stopped".

This couples live dashboards to two things this document treats as findings rather than contracts:
the group aggregation above, and the gateway's 50 % model from §13. **Changing either breaks the
labels silently**, and the breakage appears on wall panels — nothing in `pytest` covers it.

The same nine cards call `cover.stop_cover`. The four `rest_command.*_stop` entries that used to
proxy stop through Homebridge at `192.168.1.60:49694` were deleted from `rest_commands.yaml` the
same day, so the integration now owns Irismo stop end to end with no external hop.

> `192.168.1.60` is a placeholder for reference only, not a real address — this repo is public and
> carries no real network addresses. Only the port is meaningful here. See the note in `CLAUDE.md`.

Affected dashboards: `wp-06`, `wp-07`, `wp-08`,
`wp-10`, `wp-11`, `wp-36`, `wp-37`.

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
