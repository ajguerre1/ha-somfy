# HA Somfy

A Home Assistant integration for the **Somfy Connect UAI+** gateway, controlling Somfy SDN
(RS-485) motorised blinds, shades and drapes.

> **Status: in development.** Not yet installable. See [`docs/ai/planning/backlog.md`](docs/ai/planning/backlog.md).

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

## Credits

Built clean-room. Protocol behaviour was derived from Somfy's published *SDN Integration Guide*,
observable gateway responses, and prior art by
[peter-dolkens](https://github.com/peter-dolkens/somfy-uai),
[Me1000](https://github.com/Me1000/home-assistant-somfy-uai-plus) and
[philipflesher](https://github.com/philipflesher/somfy-uai-plus-hass) — with thanks.

## License

[MIT](LICENSE)
