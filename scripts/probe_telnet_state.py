#!/usr/bin/env python3
"""Is there a telnet route to an SDN Module's state? (IRIS-01, part 3)

`somfy_device.json` has the position, but it needs the pilot.htm session --
a second credential this integration deliberately does not ask for (PROTO-07).
Before accepting that cost, find out whether telnet can answer the same
question under a method we have not tried.

STRICTLY QUERY-ONLY, and structurally so: the allowlist below permits only
`status.*` / `group.*` reads. Any method containing a mutating verb, or outside
those namespaces, raises before a byte is sent. `sdn.status.position` is the
only one of these already known; the rest are guesses at sibling read methods.

    python scripts/probe_telnet_state.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_uai import DEFAULT_PORT, SECRETS_FILE, UaiProbe

# Only status/group reads. Anything else is refused below.
_ALLOWED_NAMESPACE = re.compile(r"^(sdn\.)?(status|group|system)\.[a-z]+$")
_FORBIDDEN_VERB = re.compile(r"\b(move|set|goto|preset|lock|reset|factory|write|del|add)\b", re.I)

CANDIDATES = [
    "sdn.status.detail",
    "sdn.status.state",
    "sdn.status.limits",
    "sdn.status.node",
    "sdn.status.all",
    "sdn.status.motor",
    "sdn.status.percent",
    "sdn.status.pulses",
    "system.listmethods",
    "system.methods",
]

IRISMO = "40FCFC"
SONESSE = "136EA5"


def assert_safe(method: str) -> None:
    if not _ALLOWED_NAMESPACE.match(method):
        raise RuntimeError(f"refusing {method!r}: outside the status/group/system read namespace")
    if _FORBIDDEN_VERB.search(method):
        raise RuntimeError(f"refusing {method!r}: mutating verb")


async def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    probe = UaiProbe(
        secrets["host"],
        secrets.get("port", DEFAULT_PORT),
        secrets.get("user", ""),
        secrets.get("password", ""),
        False,
    )

    for method in CANDIDATES:
        assert_safe(method)
    # Bypass probe_uai's own narrower allowlist for these vetted read methods.
    import probe_uai

    probe_uai.READ_ONLY_METHODS = frozenset(probe_uai.READ_ONLY_METHODS | set(CANDIDATES))

    await probe.connect()
    try:
        for method in CANDIDATES:
            for label, node in (("irismo", IRISMO), ("sonesse", SONESSE)):
                try:
                    reply = await probe.request(method, {"targetID": node}, timeout=5.0)
                    body = json.dumps(reply, separators=(",", ":"))
                except Exception as exc:
                    body = f"{type(exc).__name__}"
                print(f"  {method:<24} {label:<8} -> {body[:110]}")
        print()
        print("  --- known-good control ---")
        for label, node in (("irismo", IRISMO), ("sonesse", SONESSE)):
            reply = await probe.request("sdn.status.position", {"targetID": node}, timeout=5.0)
            print(f"  {'sdn.status.position':<24} {label:<8} -> {reply}")
    finally:
        await probe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
