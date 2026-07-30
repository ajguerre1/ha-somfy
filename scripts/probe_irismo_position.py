#!/usr/bin/env python3
"""Does the gateway know an Irismo's position after all? (IRIS-01)

The UAI+ web interface shows `POSITION 1000 (100 %)` for node 40.FC.FC, an
"SDN Module" -- an Irismo behind a 1811129 bridge. Telnet `sdn.status.position`
refuses all nine of those nodes with `{"error":-32600}`, which is why this
integration classifies them as non-positional and shows no state at all.

Both cannot be the whole truth. This probe finds out which surface the web UI
is reading, and on what scale.

STRICTLY QUERY-ONLY. HTTP GETs plus telnet methods from probe_uai's read-only
allowlist. Nothing here can move a blind.

    python scripts/probe_irismo_position.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_uai import DEFAULT_PORT, SECRETS_FILE, UaiProbe

HTTP_TIMEOUT = 15

IRISMO = [
    "40FD76",
    "40FD85",
    "40FD7B",
    "40FD89",
    "40FD74",
    "40FD88",
    "40FD75",
    "40FD86",
    "40FCFC",
]
# Controls: a Sonesse 50DC that reports 100 over telnet, one that reports 0, and
# the Sonesse 30 that answers `false`. If HTTP and telnet disagree on these, the
# scale question is answered without touching an Irismo at all.
SONESSE = ["136EA5", "136DAB", "07753E"]


def dotted(node_id: str) -> str:
    """40FCFC -> 40.FC.FC, the form the HTTP endpoint expects."""
    return ".".join(node_id[i : i + 2] for i in range(0, len(node_id), 2))


def http_login(host: str, web_password: str) -> int:
    """Establish the IP-bound pilot.htm session. Checks a password; sets nothing."""
    url = f"http://{host}/password.cgi?VERIFY={web_password}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
            return response.status
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def http_device(host: str, node_id: str) -> dict[str, Any] | None:
    url = f"http://{host}/somfy_device.json?{dotted(node_id)}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as err:
        return {"_error": f"{type(err).__name__}: {err}"}
    device = payload.get("DEVICE") if isinstance(payload, dict) else None
    return device if isinstance(device, dict) else {"_error": f"unexpected payload: {payload!r}"}


async def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    host = secrets["host"]

    status = http_login(host, secrets.get("web_password", ""))
    print(f"pilot.htm session: HTTP {status}\n")

    probe = UaiProbe(
        host,
        secrets.get("port", DEFAULT_PORT),
        secrets.get("user", ""),
        secrets.get("password", ""),
        False,
    )
    await probe.connect()

    rows: list[tuple[str, str, Any, Any, str]] = []
    try:
        for kind, nodes in (("SDN Module", IRISMO), ("Sonesse", SONESSE)):
            for node_id in nodes:
                # Telnet position -- expected to fail for SDN Module.
                try:
                    reply = await probe.request(
                        "sdn.status.position", {"targetID": node_id}, timeout=8.0
                    )
                    telnet: Any = reply["result"] if "result" in reply else f"ERR {reply}"
                except Exception as exc:
                    telnet = f"{type(exc).__name__}"

                device = http_device(host, node_id) or {}
                rows.append(
                    (
                        kind,
                        node_id,
                        telnet,
                        device.get("POSITION", device.get("_error", "<absent>")),
                        json.dumps(device, separators=(",", ":")),
                    )
                )
    finally:
        await probe.close()

    print(f"{'kind':<11} {'node':<8} {'telnet':<16} {'http POSITION':<16}")
    print("-" * 60)
    for kind, node_id, telnet, http_pos, _ in rows:
        print(f"{kind:<11} {node_id:<8} {telnet!s:<16} {http_pos!s:<16}")

    print()
    print("=== full HTTP payloads ===")
    for kind, node_id, _, _, raw in rows:
        print(f"  {kind:<11} {node_id}: {raw}")

    out = Path(__file__).resolve().parent / "output" / "irismo-position.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            [
                {"kind": k, "node_id": n, "telnet": str(t), "http_position": str(p), "device": raw}
                for k, n, t, p, raw in rows
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
