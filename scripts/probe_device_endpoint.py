#!/usr/bin/env python3
"""How reliable is somfy_device.json? (IRIS-01, part 2)

The first pass found the endpoint answering with the WRONG node: a request for
40.FC.FC returned a payload whose own NODE field said 13.6E.A5, and three other
nodes returned 404. If Irismo position is going to be polled from here, that
behaviour has to be understood first -- silently attributing one blind's
position to another is worse than showing nothing.

Hypothesis: the gateway holds a single "current device" buffer. The request
triggers an SDN read and the response returns whatever is in the buffer, which
may still be the previous node or may be empty.

If that is right, then the NODE field in the payload is the guard: compare it
against what was asked for, and retry on mismatch.

STRICTLY QUERY-ONLY -- HTTP GETs only, no telnet, nothing that can move a blind.

    python scripts/probe_device_endpoint.py
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SECRETS_FILE = Path(__file__).resolve().parent / "secrets.local.json"
TIMEOUT = 15

IRISMO = ["40FD76", "40FD85", "40FD7B", "40FD89", "40FD74", "40FD88", "40FD75", "40FD86", "40FCFC"]
SONESSE = ["136EA5", "136DAB"]


def dotted(node_id: str) -> str:
    return ".".join(node_id[i : i + 2] for i in range(0, len(node_id), 2))


def undotted(node: str) -> str:
    return node.replace(".", "").upper()


def get_device(host: str, node_id: str) -> tuple[int, dict[str, Any]]:
    url = f"http://{host}/somfy_device.json?{dotted(node_id)}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            device = payload.get("DEVICE") if isinstance(payload, dict) else None
            return response.status, device if isinstance(device, dict) else {}
    except urllib.error.HTTPError as err:
        return err.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return 0, {}


def login(host: str, password: str) -> int:
    try:
        with urllib.request.urlopen(
            f"http://{host}/password.cgi?VERIFY={password}", timeout=TIMEOUT
        ) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def attempt(host: str, node_id: str) -> tuple[str, str]:
    """Return (outcome, position). Outcome is ok / mismatch:<node> / http:<code>."""
    status, device = get_device(host, node_id)
    if status != 200 or not device:
        return f"http:{status}", ""
    returned = undotted(str(device.get("NODE", "")))
    position = str(device.get("POSITION", ""))
    if returned != node_id.upper():
        return f"mismatch:{returned}", position
    return "ok", position


def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    host = secrets["host"]
    print(f"pilot.htm session: HTTP {login(host, secrets.get('web_password', ''))}\n")

    print("=== 1. Same node, 6 times in a row ===")
    for node_id in ("40FCFC", "136EA5"):
        outcomes = [attempt(host, node_id) for _ in range(6)]
        print(f"  {node_id}: " + "  ".join(f"{o}{'/' + p if p else ''}" for o, p in outcomes))

    print()
    print("=== 2. Retry-until-match, whole fleet ===")
    print("  (does asking again resolve a 404 or a mismatch?)")
    rows = []
    for node_id in IRISMO + SONESSE:
        tries: list[str] = []
        position = ""
        for _ in range(5):
            outcome, pos = attempt(host, node_id)
            tries.append(outcome)
            if outcome == "ok":
                position = pos
                break
            time.sleep(0.3)
        rows.append((node_id, len(tries), tries[-1], position))
        print(f"  {node_id:<8} attempts={len(tries)}  final={tries[-1]:<18} POSITION={position}")

    resolved = [r for r in rows if r[2] == "ok"]
    print()
    print(f"  resolved with <=5 attempts : {len(resolved)}/{len(rows)}")
    print(f"  needed more than one try   : {sum(1 for r in resolved if r[1] > 1)}")

    out = Path(__file__).resolve().parent / "output" / "device-endpoint.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            [{"node_id": n, "attempts": a, "final": f, "position": p} for n, a, f, p in rows],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
