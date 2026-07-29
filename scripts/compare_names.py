#!/usr/bin/env python3
"""Cross-check telnet node names against the gateway's HTTP labels.

The gateway exposes a node's label two ways, and they were observed to
disagree: `sdn.status.info` returned a stale `name` for one node while
`GET /somfy_device.json?<dotted-node>` already had the corrected `LABEL`.

Entity names determine entity IDs, so a wrong name means a wrong entity ID and
broken dashboard references. This sweeps every node and reports any mismatch.

Read-only: HTTP GETs plus the query-only telnet probe.

    python scripts/compare_names.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_uai import DEFAULT_PORT, SECRETS_FILE, UaiProbe

HTTP_TIMEOUT = 15


def dotted(node_id: str) -> str:
    """136E33 -> 13.6E.33, the form the HTTP endpoint expects."""
    return ".".join(node_id[i : i + 2] for i in range(0, len(node_id), 2))


def http_label(host: str, node_id: str) -> str | None:
    url = f"http://{host}/somfy_device.json?{dotted(node_id)}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    device = payload.get("DEVICE") if isinstance(payload, dict) else None
    if not isinstance(device, dict):
        return None
    label = device.get("LABEL")
    return label.strip() if isinstance(label, str) else None


async def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    host = secrets["host"]

    probe = UaiProbe(
        host, secrets.get("port", DEFAULT_PORT), secrets["user"], secrets["password"], False
    )
    await probe.connect()
    try:
        nodes = await probe.ping_all()
        print(f"Comparing {len(nodes)} nodes ...\n")
        rows: list[tuple[str, str | None, str | None]] = []
        for node_id in nodes:
            report = await probe.probe_node(node_id, retries=1)
            rows.append((node_id, report.name, http_label(host, node_id)))
    finally:
        await probe.close()

    mismatches = [r for r in rows if r[1] != r[2]]
    missing_http = [r for r in rows if r[2] is None]

    print(f"{'node':<8} {'telnet name':<20} {'http LABEL':<20} status")
    print("-" * 62)
    for node_id, telnet, http in rows:
        status = "ok" if telnet == http else "MISMATCH"
        print(f"{node_id:<8} {telnet!s:<20} {http!s:<20} {status}")

    print()
    print(f"nodes            : {len(rows)}")
    print(f"http unavailable : {len(missing_http)}")
    print(f"MISMATCHES       : {len(mismatches)}")
    for node_id, telnet, http in mismatches:
        print(f"  {node_id}: telnet={telnet!r}  http={http!r}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
