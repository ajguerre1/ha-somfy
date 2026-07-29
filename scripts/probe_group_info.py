#!/usr/bin/env python3
"""Does `sdn.status.info` answer for a groupID as well as a targetID?

Testing whether the gateway conflates group and node identity in this call,
which would explain why a first-read node name can come back looking exactly
like its group's name.

Read-only: only sdn.status.info and sdn.group.get are sent.

    python scripts/probe_group_info.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_uai import DEFAULT_PORT, SECRETS_FILE, UaiProbe

GROUPS = {"01010A": "RoomI SH", "010109": "RoomI B/O", "010112": "RoomD SH"}
IRISMO = ["40FD76", "40FD85", "40FD75", "40FD88", "40FD86", "40FD89", "40FCFC"]


async def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    probe = UaiProbe(
        secrets["host"],
        secrets.get("port", DEFAULT_PORT),
        secrets["user"],
        secrets["password"],
        False,
    )
    await probe.connect()
    try:
        print("=== sdn.status.info addressed by groupID ===")
        for gid, expected in GROUPS.items():
            try:
                reply = await probe.request("sdn.status.info", {"groupID": gid}, timeout=8.0)
            except Exception as exc:
                print(f"  {gid} ({expected}): {type(exc).__name__}")
                continue
            print(f"  {gid} (web UI: {expected!r}) -> {reply}")

        print()
        print("=== sdn.status.info by targetID, third read ===")
        for node_id in IRISMO:
            try:
                reply = await probe.request("sdn.status.info", {"targetID": node_id}, timeout=8.0)
                result = reply.get("result")
                name = result.get("name") if isinstance(result, dict) else result
            except Exception as exc:
                name = f"{type(exc).__name__}"
            print(f"  {node_id} -> {name!r}")
    finally:
        await probe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
