---
name: somfy-sdn
description: Use when talking to Somfy SDN motors through a Somfy Connect UAI+ gateway (telnet JSON-RPC on port 23) — discovering nodes, reading motor type or position, addressing groups, or diagnosing blinds that show a dead position slider, a permanently unknown state, or a wrong entity name.
---

# Somfy SDN over a Connect UAI+ gateway

Measured against a live 49-node bus (HW 04.04 / FW 02.03.11), not inferred from prior art.

**Core principle: read capability, never assume it.** Not every motor on an SDN bus can report
position, and the ones that cannot are invisible to the obvious check. Every published
integration for this gateway hardcodes `OPEN|CLOSE|STOP|SET_POSITION` for all motors, which is
why Irismo blinds render with a slider that can never work.

## Transport

Telnet, TCP 23. Line-oriented JSON, one object per request, correlated by `id`.

```
User:<user>\n  →  Password:<pass>\n  →  "Connected:\n\x00"
{"method":"sdn.status.info","params":[{"targetID":"136EA5"}],"id":1002}
```

| Method | Params | Returns |
|---|---|---|
| `sdn.status.ping` | `{"targetID":"*"}` | all node IDs |
| `sdn.status.info` | `{"targetID":…}` or `{"groupID":…}` | `{"name","type"}`; groups return `name` only |
| `sdn.status.position` | `{"targetID":…}` | `0`-`100`, or `false`, or an error |
| `sdn.group.get` | `{"targetID":…}` | list of group IDs |

The `sdn.` prefix is optional — `status.info` returns an identical payload. No reason to switch.

## The five traps

**1. `params` is a list of single-key dicts**, not a dict. `[{"targetID":"X"}]`. A bare dict is
silently wrong.

**2. Irismo reports `"SDN Module"`. The string `irismo` never appears on the wire.** Irismo is a
dry-contact drapery motor with no SDN NodeType; it joins the bus through bridge P/N 1811129, and
the gateway names *the bridge*. A classifier matching `irismo` matches zero Irismo motors. This is
the finding that matters most — everything else is detail.

**2b. "Refuses position over telnet" does not mean "has no state".** Every SDN Module node answers
`sdn.status.position` with `-32600`, which reads like the end of the story. It is not: the gateway
holds an open/closed value for them and serves it from `somfy_device.json`. Commanding one flips
that value in **under two seconds** — quicker than a drape can travel — so it is *modelled from
the last command*, not measured. That makes it correct for open/closed, never intermediate (only
ever 0 or 1000), and blind to any other control path. Give such a motor state, but never a slider.

**3. `bool` subclasses `int` in Python.** `{"result": false}` means *position currently unknown*.
`isinstance(False, int)` is `True`, so a naive numeric check reads it as position 0 — a blind
reported fully closed when nothing knows where it is. Reject `bool` before any numeric check.

**4. `false` is not a capability verdict — it is a hardware smell.** On the reference bus exactly
two nodes answered `false`, and both were physically faulty; all 38 healthy positional motors
returned a number. Treat it as "inspect this motor", never as "this motor has no position".
Demoting a Sonesse on one bad reading makes its feature set flap between polls.

**4b. `false` is also the normal reply to a movement command.** `sdn.move.up`, `.down` and `.stop`
all answer `{"result":false}` on success. Do not read that as failure — check for an `error` key
instead. And `sdn.move.stop` *does* work on an SDN Module; the gateway then models that motor at
the midpoint (50 %), which is how a stopped Irismo reports.

**5. The first `sdn.status.info` for a node can return a placeholder** synthesised from its group
membership (`"RoomI SH 1"` instead of `"RoomI SH 1"`). The query itself triggers the real
read; a second call returns the truth. If entity IDs derive from the name, a first-read capture
becomes a permanently wrong ID. Read twice, and prefer the HTTP `LABEL` where available.

## Classifying capability

1. Match the `type` string, case-insensitive, whitespace-normalised.
   `sonesse`, `glydea`, `lsu`, `50dc`, `50ac` → **positional**.
   `sdn module` → **non-positional**.
2. Unknown type → probe `sdn.status.position` **once**. A number means positional; an error or
   missing `result` means non-positional; `false` is inconclusive, so retry later.
3. Never key on node ID ranges. They correlated perfectly on the reference bus and that is an
   artefact of one site's commissioning order.

Errors come back as a **bare integer** with no `result` key: `{"error":-32600,"id":1046}`.

> **Telnet replies are broadcast to every open session.** A connection that had sent only ids
> 5001-5003 received fourteen replies carrying ids 8703-8716 — another client's traffic. Since a
> reply echoes only the `id`, never the method or target, a foreign reply matching a pending
> request is indistinguishable from your own and will store one motor's state on another. **Start
> request ids at a large random offset**, not a fixed base: a counter from 1000 sweeps straight
> through the range other clients use.

## Groups

```
groupID = "0101" + f"{index:02X}"     # index is the 1-based key in GET /somfy_groups.json
```

Group 1 (`ALL`) is a broadcast with no stored membership — skip it in discovery. Build membership
from each node's own `sdn.group.get` rather than any group-side listing; it is the more reliable
field, and it is what catches a node whose name disagrees with where it actually lives.

## HTTP surface (port 80)

| Path | Auth | Use |
|---|---|---|
| `somfy_groups.json` | none | group names — the only source |
| `about.json` | none | firmware, serial |
| `somfy_device.json?13.6E.A5` | **session** | per-node `LABEL`, `TYPE`, position |
| `somfy_devices.json` | session | all labels in one request |

Session auth is `GET /password.cgi?VERIFY=<web password>` — a **separate credential** from telnet,
and it sets no cookie, so the session is **bound to the client IP** and expires on its own.

Three things about that endpoint will cost you a day each:

- **Test auth from the machine that will run the code.** A workstation with the web UI open in a
  browser already has a session, and scripts run there inherit it silently. That is how this
  endpoint got recorded as unauthenticated, and why the integration's label fetching was dead in
  production without anyone noticing.
- **The login response proves nothing.** It answers 200 normally but can drop the connection while
  still authenticating. Send it, ignore the result, and let the next read decide.
- **Send the password unencoded.** Percent-encoding it is rejected with 403.
- **One session at a time, bound to the client IP.** A second client logging in evicts the first,
  so a probe run while the integration is polling will make the integration fail, and vice versa.
  Do not debug both at once and conclude the endpoint is flaky.

**It answers with the wrong node.** A request for one node sometimes returns another node's
payload, or 404. The payload carries its own `NODE` field — compare it against what you asked for
and retry on mismatch. Over 11 nodes: all resolved within five attempts, two needed more than one.

> **A stale session produces the identical symptom.** It does *not* answer 403 — it answers 200
> with someone else's payload. So "wrong node" is ambiguous between "buffer lagging" and "not
> logged in", and a client that re-authenticates only on 403 will deadlock: the guard rejects
> every reply, nothing ever looks like an auth failure, and it retries a dead session forever.
> **Re-authenticate after N rejected reads, not on a status code.** This cost a release.

**`POSITION` is a display string on two different scales.** `"12406 (100 %)"` for a Sonesse is
encoder pulses bounded by that motor's `LIMITS DOWN`; `"1000 (100 %)"` for an SDN Module is a fixed
0–1000. Parse the parenthesised percentage. Never the leading number.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Hardcoding `supported_features` | Dead slider on every non-positional motor |
| Matching `irismo` | Matches nothing; all 9 Irismo misclassified as positional |
| Reading `-32600` as "no state exists" | Irismo entities sit at `unknown` forever, though the gateway knows |
| Trusting a payload without checking `NODE` | One blind's state silently shown on another |
| Parsing the leading number in `POSITION` | 12406 read as a percentage |
| Treating `false` as 0 | Blind reports fully closed at an unknown position |
| Reading `info` once | Permanently wrong entity ID from a group-derived placeholder |
| Dropping a node that missed one ping | Entities flicker to unavailable; discovery is a union over time, not a snapshot |
| Assuming the bus is slow | It is not — 149 requests in 5.0 s, mean 0.03 s, zero retries |
| Assuming `local_push` | Zero unsolicited notifications, measured with nothing moving and re-confirmed during commanded movement; `local_polling` is honest |
| Correlating replies by a low, fixed id counter | Another session's reply accepted as yours — one blind's state on another |
| Probing the web interface while the integration runs | One web session at a time; each evicts the other, which reads as "flaky HTTP" |

## Position polarity

Somfy uses 0 = open / 100 = closed. Home Assistant is the inverse. The data cannot settle this —
motors sit at exactly 0 or 100 — so **move one motor and look at it** rather than guessing. Funnel
the conversion through one helper so confirming it is a one-line change.
