#!/usr/bin/env python3
"""Settle the two remaining protocol questions.

PROTO-09  Does the gateway accept methods without the `sdn.` prefix?
          Another client uses `status.info`; if both forms work it is a usable
          fallback, and if not the claim should be struck from the notes.

PROTO-07  `GET /somfy_devices.json` returns 403 unauthenticated. Is it reachable
          with the telnet credentials? It would give the whole inventory in one
          request instead of one per node.

Read-only throughout: only status/group queries and HTTP GETs.

    python scripts/probe_open_questions.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_uai import DEFAULT_PORT, READ_ONLY_METHODS, SECRETS_FILE, UaiProbe

SAMPLE_NODE = "136EA5"
HTTP_TIMEOUT = 15

# Both spellings of each read-only call. The bare forms are already in the
# probe's allowlist, so nothing here can move a motor.
METHOD_PAIRS = [
    ("sdn.status.info", "status.info"),
    ("sdn.status.position", "status.position"),
    ("sdn.group.get", "group.get"),
]


def http_get(url: str, credentials: tuple[str, str] | None = None) -> tuple[int, str]:
    """GET a URL, optionally with HTTP basic auth. Returns (status, body head)."""
    request = urllib.request.Request(url)
    if credentials is not None:
        token = base64.b64encode(":".join(credentials).encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")[:400]
    except urllib.error.HTTPError as err:
        return err.code, err.reason or ""
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return 0, str(err)


async def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    host = secrets["host"]
    credentials = (secrets["user"], secrets["password"])

    print("=== PROTO-09: bare method prefix ===")
    probe = UaiProbe(host, secrets.get("port", DEFAULT_PORT), *credentials, False)
    await probe.connect()
    try:
        for prefixed, bare in METHOD_PAIRS:
            assert bare in READ_ONLY_METHODS, f"{bare} is not allowlisted"
            results = {}
            for method in (prefixed, bare):
                try:
                    reply = await probe.request(method, {"targetID": SAMPLE_NODE}, timeout=8.0)
                    results[method] = reply
                except Exception as exc:
                    results[method] = f"{type(exc).__name__}"

            # Compare the payloads, not the whole replies: the `id` field
            # necessarily differs between two requests, so comparing the raw
            # dicts always reports a difference and tells you nothing.
            def payload(reply: object) -> object:
                return reply.get("result") if isinstance(reply, dict) else reply

            same = payload(results[prefixed]) == payload(results[bare])
            print(f"  {prefixed:<22} -> {payload(results[prefixed])}")
            print(f"  {bare:<22} -> {payload(results[bare])}")
            print(f"  {'':<22}    same result: {same}")
            print()
    finally:
        await probe.close()

    print("=== PROTO-07: /somfy_devices.json ===")
    url = f"http://{host}/somfy_devices.json"
    status, body = http_get(url)
    print(f"  no auth        -> HTTP {status}  {body[:120]!r}")
    status, body = http_get(url, credentials)
    print(f"  basic auth     -> HTTP {status}  {body[:200]!r}")

    print()
    print("=== other endpoints the web UI uses (read-only) ===")
    for path in (
        "somfy_groups.json",
        "somfy_controls.json",
        "about.json",
        f"somfy_presets.json?{'.'.join(SAMPLE_NODE[i : i + 2] for i in range(0, 6, 2))}",
    ):
        status, body = http_get(f"http://{host}/{path}")
        print(f"  {path:<34} -> HTTP {status}  {body[:110]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
