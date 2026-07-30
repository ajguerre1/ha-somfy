#!/usr/bin/env python3
"""Does telnet push Irismo state, and does STOP work? (IRIS-07 / IRIS-08)

THIS SCRIPT MOVES A BLIND. It is the only script in this repository that does.
Run only with the owner's explicit, current agreement.

Two questions, one experiment:

1. **Does the gateway push state on telnet?** PERF-04 concluded it does not, but
   that was measured during a query-only probe with nothing moving. Other
   control systems show Irismo state over telnet alone, which would be explained
   by a notification emitted when a motor is commanded. Every byte on the stream
   is captured throughout, so a push cannot be missed.
2. **Does `sdn.move.stop` work on an SDN Module, and where does the gateway's
   model land?** The owner reports a stopped Irismo maps to 50 %.

Safety, in order:

* The target is hardcoded to ONE node and checked before every send.
* Only three methods are permitted, checked before every send.
* The sequence restores the blind to the state it started in.

    python scripts/probe_irismo_stop.py --yes-move-a-blind
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SECRETS = Path(__file__).resolve().parent / "secrets.local.json"

TARGET = "40FCFC"  # RoomD Hall SH -- single-motor hallway drape
PERMITTED = {"sdn.move.down", "sdn.move.stop", "sdn.move.up"}
TRAVEL_BEFORE_STOP = 4.0  # owner's estimate of a safe mid-travel moment
OBSERVE = 6.0


def vet(method: str, target: str) -> None:
    if method not in PERMITTED:
        raise RuntimeError(f"refusing {method!r}: not one of {sorted(PERMITTED)}")
    if target != TARGET:
        raise RuntimeError(f"refusing to command {target!r}: this script only touches {TARGET}")


class Session:
    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.log: list[tuple[float, str, str]] = []
        self._t0 = 0.0
        self._task: asyncio.Task | None = None

    def _stamp(self) -> float:
        return round(time.monotonic() - self._t0, 2)

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        await self._read_until("User:")
        await self._send(self.user)
        await self._read_until("Password:")
        await self._send(self.password)
        await self._read_until("Connected:")
        self._t0 = time.monotonic()

    async def _read_until(self, needle: str) -> str:
        buf = ""
        while needle not in buf:
            chunk = await asyncio.wait_for(self.reader.read(4096), timeout=15)
            if not chunk:
                raise ConnectionError("closed during handshake")
            buf += chunk.decode("ascii", errors="replace")
        return buf

    async def _send(self, line: str) -> None:
        self.writer.write((line + "\r\n").encode("ascii"))
        await self.writer.drain()

    async def _listen(self) -> None:
        """Capture EVERY line, solicited or not, until cancelled."""
        while True:
            try:
                raw = await self.reader.readline()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log.append((self._stamp(), "ERR", f"{type(exc).__name__}: {exc}"))
                return
            if not raw:
                self.log.append((self._stamp(), "ERR", "stream closed"))
                return
            text = raw.decode("ascii", errors="replace").strip().strip("\x00").strip()
            if text:
                self.log.append((self._stamp(), "<--", text))

    def start_listening(self) -> None:
        self._task = asyncio.create_task(self._listen())

    async def command(self, method: str, msg_id: int) -> None:
        vet(method, TARGET)
        payload = json.dumps(
            {"method": method, "params": [{"targetID": TARGET}], "id": msg_id},
            separators=(",", ":"),
        )
        self.log.append((self._stamp(), "-->", payload))
        await self._send(payload)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self.writer:
            self.writer.close()


def http_position(host: str, web_password: str) -> str:
    dotted = ".".join(TARGET[i : i + 2] for i in range(0, len(TARGET), 2))
    login = f"http://{host}/password.cgi?VERIFY={web_password}"
    with contextlib.suppress(Exception):
        urllib.request.urlopen(login, timeout=10).read()
    for _ in range(6):
        try:
            payload = json.loads(
                urllib.request.urlopen(f"http://{host}/somfy_device.json?{dotted}", timeout=10)
                .read()
                .decode()
            )
            d = payload.get("DEVICE", {})
            if str(d.get("NODE", "")).replace(".", "").upper() == TARGET:
                return str(d.get("POSITION"))
        except Exception:
            pass
        time.sleep(0.4)
    return "<unresolved>"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes-move-a-blind", action="store_true", required=True)
    ap.parse_args()

    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    host, web_pw = s["host"], s.get("web_password", "")

    print(f"target {TARGET} (RoomD Hall SH)   started {datetime.now(UTC):%H:%M:%SZ}")
    print(f"HTTP position before : {http_position(host, web_pw)}\n")

    sess = Session(host, s.get("port", 23), s.get("user", ""), s.get("password", ""))
    await sess.connect()
    sess.start_listening()
    try:
        await sess.command("sdn.move.down", 5001)  # close
        await asyncio.sleep(TRAVEL_BEFORE_STOP)
        await sess.command("sdn.move.stop", 5002)  # stop mid-travel
        await asyncio.sleep(OBSERVE)
        mid = http_position(host, web_pw)
        await asyncio.sleep(1.0)
        await sess.command("sdn.move.up", 5003)  # restore to open
        await asyncio.sleep(12.0)
    finally:
        await sess.close()

    print("=== telnet stream, every line, seconds since login ===")
    for stamp, direction, text in sess.log:
        print(f"  {stamp:>6.2f}s {direction} {text}")

    solicited = {5001, 5002, 5003}
    unsolicited = []
    for _, direction, text in sess.log:
        if direction != "<--":
            continue
        try:
            msg = json.loads(text)
            if isinstance(msg, dict) and msg.get("id") in solicited:
                continue
        except Exception:
            pass
        unsolicited.append(text)

    print()
    print(f"=== UNSOLICITED lines (not a reply to our 3 commands): {len(unsolicited)} ===")
    for line in unsolicited:
        print(f"  {line}")

    print()
    print(f"HTTP position while stopped : {mid}")
    print(f"HTTP position after restore : {http_position(host, web_pw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
