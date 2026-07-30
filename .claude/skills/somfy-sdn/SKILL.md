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

**3. `bool` subclasses `int` in Python.** `{"result": false}` means *position currently unknown*.
`isinstance(False, int)` is `True`, so a naive numeric check reads it as position 0 — a blind
reported fully closed when nothing knows where it is. Reject `bool` before any numeric check.

**4. `false` is not a capability verdict — it is a hardware smell.** On the reference bus exactly
two nodes answered `false`, and both were physically faulty; all 38 healthy positional motors
returned a number. Treat it as "inspect this motor", never as "this motor has no position".
Demoting a Sonesse on one bad reading makes its feature set flap between polls.

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
| `somfy_device.json?13.6E.A5` | none | per-node `LABEL`, `TYPE`, position |
| `about.json` | none | firmware, serial |
| `somfy_devices.json` | session | all labels in one request |

Session auth is `GET /password.cgi?VERIFY=<web password>` — a **separate credential** from telnet,
and it sets no cookie, so the session is bound to the client IP.

## Common mistakes

| Mistake | Consequence |
|---|---|
| Hardcoding `supported_features` | Dead slider on every non-positional motor |
| Matching `irismo` | Matches nothing; all 9 Irismo misclassified as positional |
| Treating `false` as 0 | Blind reports fully closed at an unknown position |
| Reading `info` once | Permanently wrong entity ID from a group-derived placeholder |
| Dropping a node that missed one ping | Entities flicker to unavailable; discovery is a union over time, not a snapshot |
| Assuming the bus is slow | It is not — 149 requests in 5.0 s, mean 0.03 s, zero retries |
| Assuming `local_push` | Zero unsolicited notifications in 149 requests; `local_polling` is honest |

## Position polarity

Somfy uses 0 = open / 100 = closed. Home Assistant is the inverse. The data cannot settle this —
motors sit at exactly 0 or 100 — so **move one motor and look at it** rather than guessing. Funnel
the conversion through one helper so confirming it is a one-line change.
