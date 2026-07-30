#!/usr/bin/env python3
"""Can telnet report an Irismo's state after all? (IRIS-07)

Other control systems -- Control4, Crestron, RTI, Elan, Lutron -- integrate
Irismo behind SDN bridges using the telnet credentials alone, and show
open/closed state. That is strong evidence of a route this project has not
found: `sdn.status.position` answers `{"error":-32600}` for all nine SDN Module
nodes, and IRIS-01 concluded HTTP was the only source.

That conclusion rested on *single* reads. This gateway is already known to
answer the FIRST `sdn.status.info` for a node with a placeholder, because the
query itself triggers the underlying SDN read and only a later call returns the
truth (see §10 of the protocol findings). If position behaves the same way, a
one-shot probe would look exactly like a permanent refusal.

Hypotheses, in order of cheapness:

  A. Position needs repeated polling -- ask the same node 8 times.
  B. Position answers for a groupID as well as a targetID, the way
     `sdn.status.info` does.
  C. `sdn.status.info` returns more fields for an SDN Module than the
     {name, type} this project reads, and state is among them.
  D. An HTTP read primes the gateway, after which telnet answers.
  E. Some other read method in the status namespace.

STRICTLY QUERY-ONLY. Only `status.*` and `group.*` reads are permitted below,
enforced before anything is sent. Nothing here can move a blind.

    python scripts/probe_irismo_telnet.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_uai
from probe_uai import DEFAULT_PORT, SECRETS_FILE, UaiProbe

_ALLOWED = re.compile(r"^(sdn\.)?(status|group)\.[a-z]+$")
_FORBIDDEN = re.compile(r"\b(move|set|goto|preset|lock|reset|factory|write|del|add)\b", re.I)

EXTRA_METHODS = [
    "sdn.status.level",
    "sdn.status.value",
    "sdn.status.get",
    "sdn.status.report",
    "sdn.status.percentage",
]

IRISMO = ["40FCFC", "40FD76", "40FD88"]
IRISMO_GROUP = "010112"  # RoomD SH -- sole member 40FCFC
SONESSE = "136EA5"


def vet(method: str) -> None:
    if not _ALLOWED.match(method) or _FORBIDDEN.search(method):
        raise RuntimeError(f"refusing {method!r}: not a status/group read")


def http_position(host: str, node: str, web_password: str) -> str:
    dotted = ".".join(node[i : i + 2] for i in range(0, len(node), 2))
    with contextlib.suppress(Exception):
        urllib.request.urlopen(
            f"http://{host}/password.cgi?VERIFY={web_password}", timeout=10
        ).read()
    for _ in range(5):
        try:
            payload = json.loads(
                urllib.request.urlopen(f"http://{host}/somfy_device.json?{dotted}", timeout=10)
                .read()
                .decode()
            )
            device = payload.get("DEVICE", {})
            if str(device.get("NODE", "")).replace(".", "").upper() == node:
                return str(device.get("POSITION"))
        except Exception:
            pass
    return "<unresolved>"


async def ask(probe: UaiProbe, method: str, params: dict) -> str:
    try:
        reply = await probe.request(method, params, timeout=6.0)
    except Exception as exc:
        return f"{type(exc).__name__}"
    return json.dumps({k: v for k, v in reply.items() if k != "id"}, separators=(",", ":"))


async def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    host = secrets["host"]

    for m in EXTRA_METHODS:
        vet(m)
    probe_uai.READ_ONLY_METHODS = frozenset(probe_uai.READ_ONLY_METHODS | set(EXTRA_METHODS))

    probe = UaiProbe(
        host,
        secrets.get("port", DEFAULT_PORT),
        secrets.get("user", ""),
        secrets.get("password", ""),
        False,
    )
    await probe.connect()
    try:
        print("=== A. repeated sdn.status.position on the same Irismo node ===")
        print("    (does the gateway answer once the read has been triggered?)")
        for node in IRISMO:
            answers = []
            for _ in range(8):
                answers.append(await ask(probe, "sdn.status.position", {"targetID": node}))
                await asyncio.sleep(0.5)
            uniq = sorted(set(answers))
            print(f"  {node}: {len(uniq)} distinct over 8 reads -> {uniq}")

        print()
        print("=== control: the same call on a Sonesse ===")
        print(f"  {SONESSE}: {await ask(probe, 'sdn.status.position', {'targetID': SONESSE})}")

        print()
        print("=== B. position addressed by groupID ===")
        for gid in (IRISMO_GROUP, "01010A"):
            print(f"  groupID {gid}: {await ask(probe, 'sdn.status.position', {'groupID': gid})}")

        print()
        print("=== C. full sdn.status.info payload for an Irismo (all keys) ===")
        for node in IRISMO[:2]:
            first = await ask(probe, "sdn.status.info", {"targetID": node})
            second = await ask(probe, "sdn.status.info", {"targetID": node})
            print(f"  {node} 1st: {first}")
            print(f"  {node} 2nd: {second}")
        print(
            f"  {SONESSE} (Sonesse, for comparison): "
            f"{await ask(probe, 'sdn.status.info', {'targetID': SONESSE})}"
        )

        print()
        print("=== D. HTTP read first, then telnet position ===")
        node = IRISMO[0]
        print(f"  HTTP says {node} = {http_position(host, node, secrets.get('web_password', ''))}")
        for attempt in (1, 2, 3):
            print(
                f"  telnet attempt {attempt}: "
                f"{await ask(probe, 'sdn.status.position', {'targetID': node})}"
            )
            await asyncio.sleep(0.4)

        print()
        print("=== E. other status-namespace reads ===")
        for method in EXTRA_METHODS:
            print(f"  {method:<26} {await ask(probe, method, {'targetID': IRISMO[0]})}")
    finally:
        await probe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
