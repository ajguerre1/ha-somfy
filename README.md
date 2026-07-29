# HA Somfy

A Home Assistant integration for the **Somfy Connect UAI+** gateway, controlling Somfy SDN
(RS-485) motorised blinds, shades and drapes.

> **Status: pre-release.** Installable via HACS, but not yet validated against live hardware.
> One known open question: position polarity is unconfirmed, so the open/closed direction may
> be inverted until a motor is moved and observed. See
> [`docs/ai/planning/backlog.md`](docs/ai/planning/backlog.md) (PROTO-08).

## Why this exists

Three community integrations already target the UAI+, and all three assume every motor reports
its position. That assumption breaks **Irismo** motors.

Irismo has no SDN NodeType. It is a dry-contact drapery motor that joins the SDN bus only through
Somfy's RS485 bridge module (P/N **1811129**), which supports open, close, stop and group
addresses — **and nothing else**. There is no position feedback to read. Existing integrations
nevertheless advertise `SET_POSITION` for every node, so Irismo blinds appear in Home Assistant
with a dead position slider and a permanently unknown state.

This integration models capability instead of assuming it: it asks the gateway what each node is,
verifies the answer, and builds each entity from what that node can actually do.

## Design principles

- **Capability, not allowlist.** Motor type comes from the gateway's own `sdn.status.info`
  reply. Unrecognised hardware is verified with a position probe and degrades to working
  open/close/stop rather than a broken slider.
- **Automatic discovery.** Motors and groups are found via `sdn.status.ping` / `sdn.group.get`.
  No hand-typed node addresses.
- **Groups are first-class.** Group covers alongside motor covers, with membership recorded per motor.
- **Quiet by default.** State is written only when a value actually changes, and only
  position-capable motors are polled. Large panel fleets are sensitive to state-change fan-out.
- **No external dependencies.** The protocol client is vendored in-repo, so `manifest.json`
  declares no `requirements` and there is no `git+https` dependency to rot.

## Hardware

| | |
|---|---|
| Gateway | Somfy Connect UAI+ (Converging Systems OEM firmware) |
| Transport | JSON-RPC over telnet, TCP 23 |
| Motors | Sonesse (position feedback) · Irismo via 1811129 bridge (open/close/stop only) |

The gateway reports Irismo motors with the type string **`SDN Module`** — the word
"Irismo" never appears on the wire, because the gateway names the bridge rather than the
motor behind it. A classifier keyed on "irismo" matches none of them.

## Installation

**HACS (recommended)** — HACS → ⋮ → *Custom repositories* → add
`https://github.com/ajguerre1/ha-somfy` as an **Integration**, then install *HA Somfy* and
restart Home Assistant.

**Manual** — copy `custom_components/ha_somfy/` into your Home Assistant `config/custom_components/`
directory and restart.

Then *Settings → Devices & Services → Add Integration → HA Somfy*, and enter the gateway's
host and telnet credentials. Motors and groups are discovered automatically.

## What you get

- **One cover per group**, enabled by default — these are what day-to-day control uses.
- **One cover per motor**, registered but **disabled by default**. Enable any of them from the
  entity settings. They start disabled so a large installation does not add state-change
  traffic you did not ask for.
- **One device per motor**, showing its reported model, so Irismo units are identifiable at
  a glance.
- **Diagnostics** with credentials redacted, listing every node, its type, and the capability
  derived from it.

## Options

*Poll interval* (default 60 s) controls how often position-capable motors are read. Motors
without position feedback are never polled.

## Development

```bash
pip install -r requirements-test.txt
pytest tests/          # HA-dependent tests need Linux; see below
ruff check . && ruff format --check .
```

Home Assistant cannot be imported on Windows (`homeassistant.runner` imports POSIX-only
`fcntl`), so `tests/ha/` is skipped there automatically and runs in CI on Ubuntu. The
vendored client under `custom_components/ha_somfy/uai/` has no Home Assistant imports and
tests on any platform.

`scripts/probe_uai.py` is a standalone, **query-only** inventory tool for the gateway. It
cannot move a motor: an allowlist gates every outbound method, with a test proving it.

## Credits

Built clean-room. Protocol behaviour was derived from Somfy's published *SDN Integration Guide*,
observable gateway responses, and prior art by
[peter-dolkens](https://github.com/peter-dolkens/somfy-uai),
[Me1000](https://github.com/Me1000/home-assistant-somfy-uai-plus) and
[philipflesher](https://github.com/philipflesher/somfy-uai-plus-hass) — with thanks.

## License

[MIT](LICENSE)
