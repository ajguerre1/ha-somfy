#!/usr/bin/env python3
"""Read-only inventory probe for the Somfy Connect UAI+ gateway.

STRICTLY QUERY-ONLY. Every outbound method is checked against READ_ONLY_METHODS
before it is sent; anything else raises before a byte leaves the socket. These
are real blinds in an occupied home, so "we intended not to move anything" is
not good enough -- movement must be structurally impossible.

What this answers (see docs/ai/planning/backlog.md):
  PROTO-02  what `sdn.status.info` reports for an Irismo node
  PROTO-03  whether `params` is a list of single-key dicts or a bare dict
  PROTO-04  the group addressing scheme
  PROTO-05  whether all nodes answer, and what retry policy is needed

Usage:
    python scripts/probe_uai.py                      # reads scripts/secrets.local.json
    python scripts/probe_uai.py --host 192.168.1.50 --user U --password P
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Safety gate. Read-only methods only -- no move/set/preset methods, ever.
# --------------------------------------------------------------------------
READ_ONLY_METHODS = frozenset(
    {
        "sdn.status.ping",
        "sdn.status.info",
        "sdn.status.position",
        "sdn.group.get",
        "sdn.group.members",
        # bare forms: philipflesher's client omits the "sdn." prefix and the
        # gateway reportedly accepts both. Worth confirming.
        "status.ping",
        "status.info",
        "status.position",
        "group.get",
    }
)

_FORBIDDEN_HINT = re.compile(r"\b(move|set|ip|preset|lock|reset|factory|write)\b", re.I)

DEFAULT_PORT = 23
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "scripts" / "output"
SECRETS_FILE = REPO_ROOT / "scripts" / "secrets.local.json"


class UnsafeMethodError(RuntimeError):
    """Raised when a non-read-only method is about to be sent."""


def assert_read_only(method: str) -> None:
    """Fail closed: unknown methods are rejected even if they look harmless."""
    if method not in READ_ONLY_METHODS:
        raise UnsafeMethodError(
            f"Refusing to send {method!r}: not in the read-only allowlist. "
            "This probe must never move a motor."
        )
    if _FORBIDDEN_HINT.search(method):
        raise UnsafeMethodError(
            f"Refusing to send {method!r}: matches a mutating-verb pattern."
        )


# --------------------------------------------------------------------------


@dataclass
class NodeReport:
    node_id: str
    name: str | None = None
    type_string: str | None = None
    info_error: str | None = None
    position: Any = None
    position_error: str | None = None
    groups: list[str] = field(default_factory=list)
    groups_error: str | None = None
    info_attempts: int = 1

    @property
    def positional(self) -> bool:
        """True only for a real numeric position.

        `bool` subclasses `int` in Python, so a naive isinstance(x, int) check
        counts the gateway's `False` reply as a valid position of zero. Two
        Sonesse 30 nodes really do reply `False`, so this is not hypothetical.
        """
        if isinstance(self.position, bool):
            return False
        return isinstance(self.position, (int, float))


class Transcript:
    """Records the wire conversation with the password redacted."""

    def __init__(self, secret: str) -> None:
        self._secret = secret
        self.lines: list[str] = []

    def add(self, direction: str, payload: str) -> None:
        safe = payload.replace(self._secret, "***REDACTED***") if self._secret else payload
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        self.lines.append(f"{stamp} {direction} {safe!r}")


class UaiProbe:
    def __init__(self, host: str, port: int, user: str, password: str, verbose: bool) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.verbose = verbose
        self.transcript = Transcript(password)
        self.notifications: list[str] = []
        self.timings: list[tuple[str, float]] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._msg_id = 1000
        self.params_shape = "list"  # confirmed at runtime by _detect_params_shape

    # -- transport ---------------------------------------------------------

    async def connect(self, timeout: float = 15.0) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=timeout
        )
        banner = await self._read_until("User:", timeout=timeout)
        self.transcript.add("<--", banner)
        await self._send_raw(self.user)
        prompt = await self._read_until("Password:", timeout=timeout)
        self.transcript.add("<--", prompt)
        await self._send_raw(self.password)
        welcome = await self._read_until("Connected:", timeout=timeout)
        self.transcript.add("<--", welcome)

    async def _read_until(self, needle: str, timeout: float) -> str:
        """Read until a prompt substring appears. Prompts are not newline-terminated."""
        assert self._reader is not None
        buf = ""
        deadline = time.monotonic() + timeout
        while needle not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {needle!r}; got {buf!r}")
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining)
            if not chunk:
                raise ConnectionError(f"connection closed waiting for {needle!r}")
            buf += chunk.decode("ascii", errors="replace")
        return buf

    async def _send_raw(self, line: str) -> None:
        assert self._writer is not None
        self.transcript.add("-->", line)
        self._writer.write((line + "\r\n").encode("ascii"))
        await self._writer.drain()

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _encode_params(self, params: dict[str, Any], shape: str) -> Any:
        if shape == "list":
            return [{k: v} for k, v in params.items()]
        return dict(params)

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = 10.0,
        shape: str | None = None,
    ) -> dict[str, Any]:
        """Send one read-only request and wait for the matching id."""
        assert_read_only(method)
        assert self._reader is not None

        msg_id = self._next_id()
        payload = {
            "method": method,
            "params": self._encode_params(params, shape or self.params_shape),
            "id": msg_id,
        }
        encoded = json.dumps(payload, separators=(",", ":"))
        started = time.monotonic()
        await self._send_raw(encoded)

        deadline = started + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.timings.append((method, time.monotonic() - started))
                raise TimeoutError(f"no reply to {method} id={msg_id} within {timeout}s")
            try:
                raw = await asyncio.wait_for(self._reader.readline(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                self.timings.append((method, time.monotonic() - started))
                raise TimeoutError(f"no reply to {method} id={msg_id}") from exc
            if not raw:
                raise ConnectionError("connection closed mid-request")

            text = raw.decode("ascii", errors="replace").strip()
            if not text:
                continue
            self.transcript.add("<--", text)

            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                # Heartbeats and push notifications are not JSON. Keep them.
                self.notifications.append(text)
                continue

            if isinstance(msg, dict) and msg.get("id") == msg_id:
                self.timings.append((method, time.monotonic() - started))
                return msg
            self.notifications.append(text)

    # -- probe steps -------------------------------------------------------

    async def detect_params_shape(self, sample_node: str) -> str:
        """PROTO-03: settle whether params is a list of single-key dicts or a dict."""
        for shape in ("list", "dict"):
            try:
                reply = await self.request(
                    "sdn.status.info", {"targetID": sample_node}, timeout=8.0, shape=shape
                )
            except (TimeoutError, ConnectionError):
                continue
            if "result" in reply and reply["result"] not in (None, {}, []):
                self.params_shape = shape
                return shape
        self.params_shape = "list"
        return "unknown"

    async def ping_all(self, timeout: float = 45.0) -> list[str]:
        reply = await self.request("sdn.status.ping", {"targetID": "*"}, timeout=timeout)
        result = reply.get("result")
        if isinstance(result, list):
            return [str(n) for n in result]
        return []

    async def probe_node(self, node_id: str, retries: int = 2) -> NodeReport:
        report = NodeReport(node_id=node_id)

        for attempt in range(1, retries + 2):
            report.info_attempts = attempt
            try:
                reply = await self.request("sdn.status.info", {"targetID": node_id}, timeout=10.0)
                result = reply.get("result")
                if isinstance(result, dict):
                    report.name = result.get("name")
                    report.type_string = result.get("type")
                    report.info_error = None
                    break
                report.info_error = f"unexpected result: {result!r}"
            except (TimeoutError, ConnectionError) as exc:
                report.info_error = f"{type(exc).__name__}: {exc}"
            if attempt <= retries:
                await asyncio.sleep(0.4)

        # Position. A timeout or error here is a SIGNAL, not a failure --
        # it is exactly how a non-positional Irismo node is expected to behave.
        try:
            reply = await self.request("sdn.status.position", {"targetID": node_id}, timeout=8.0)
            if "result" in reply:
                report.position = reply["result"]
            else:
                report.position_error = f"no result key: {reply!r}"
        except (TimeoutError, ConnectionError) as exc:
            report.position_error = f"{type(exc).__name__}: {exc}"

        try:
            reply = await self.request("sdn.group.get", {"targetID": node_id}, timeout=10.0)
            result = reply.get("result")
            if isinstance(result, list):
                report.groups = [str(g) for g in result]
            else:
                report.groups_error = f"unexpected result: {result!r}"
        except (TimeoutError, ConnectionError) as exc:
            report.groups_error = f"{type(exc).__name__}: {exc}"

        return report

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001 - closing best-effort
                pass


# --------------------------------------------------------------------------


def load_secrets() -> dict[str, Any]:
    if SECRETS_FILE.exists():
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    return {}


def summarise(reports: list[NodeReport], shape: str, groups_seen: dict[str, list[str]]) -> str:
    out: list[str] = []
    positional = [r for r in reports if r.positional]
    non_positional = [r for r in reports if not r.positional]
    by_type: dict[str, list[NodeReport]] = defaultdict(list)
    for r in reports:
        by_type[r.type_string or "<no type reported>"].append(r)

    out.append("")
    out.append("=" * 78)
    out.append(f"NODES DISCOVERED: {len(reports)}")
    out.append(f"PARAMS WIRE SHAPE (PROTO-03): {shape}")
    out.append("=" * 78)

    out.append("")
    out.append("--- BY TYPE STRING (PROTO-02) ---")
    for type_string, group in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        pos = sum(1 for r in group if r.positional)
        out.append(f"  {type_string!r}: {len(group)} node(s), {pos} reporting position")
        for r in group:
            pos_repr = r.position if r.positional else f"NO POSITION ({r.position_error or 'n/a'})"
            out.append(f"      {r.node_id}  {r.name!r}  -> {pos_repr}")

    out.append("")
    out.append("--- CAPABILITY SPLIT ---")
    out.append(f"  positional     : {len(positional)}")
    out.append(f"  non-positional : {len(non_positional)}")

    out.append("")
    out.append("--- GROUP MEMBERSHIP (PROTO-04) ---")
    if groups_seen:
        for gid, members in sorted(groups_seen.items()):
            out.append(f"  {gid}: {len(members)} member(s) -> {', '.join(members)}")
    else:
        out.append("  (no group memberships returned)")

    failed = [r for r in reports if r.info_error]
    retried = [r for r in reports if r.info_attempts > 1 and not r.info_error]
    out.append("")
    out.append("--- RELIABILITY (PROTO-05) ---")
    out.append(f"  info failed after retries : {len(failed)}")
    out.append(f"  info needed a retry       : {len(retried)}")
    if failed:
        for r in failed:
            out.append(f"      {r.node_id}: {r.info_error}")
    return "\n".join(out)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--limit", type=int, help="probe only the first N nodes")
    parser.add_argument(
        "--nodes",
        help="comma-separated node IDs to probe instead of the full bus (e.g. 077537,07753E)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="probe each node N times, to tell a transient reply from a persistent one",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    secrets = load_secrets()
    host = args.host or secrets.get("host")
    port = args.port or secrets.get("port", DEFAULT_PORT)
    user = args.user or secrets.get("user", "")
    password = args.password or secrets.get("password", "")

    if not host:
        print(
            f"No host. Pass --host or create {SECRETS_FILE} "
            '{"host": "...", "user": "...", "password": "..."}',
            file=sys.stderr,
        )
        return 2

    probe = UaiProbe(host, port, user, password, args.verbose)
    started = datetime.now(timezone.utc)
    print(f"Connecting to {host}:{port} ...")

    try:
        await probe.connect()
        print("Authenticated.")

        print("Discovering nodes (sdn.status.ping '*') -- this can take a while ...")
        nodes = await probe.ping_all()
        print(f"  -> {len(nodes)} node(s): {', '.join(nodes) if nodes else '(none)'}")

        if not nodes:
            print("No nodes returned; nothing further to probe.", file=sys.stderr)
            return 1

        shape = await probe.detect_params_shape(nodes[0])
        print(f"  -> params wire shape: {shape}")

        if args.nodes:
            wanted = [n.strip() for n in args.nodes.split(",") if n.strip()]
            missing = [n for n in wanted if n not in nodes]
            if missing:
                print(f"  !! not present on the bus: {', '.join(missing)}", file=sys.stderr)
            targets = [n for n in wanted if n in nodes]
        elif args.limit:
            targets = nodes[: args.limit]
        else:
            targets = nodes

        reports: list[NodeReport] = []
        for round_index in range(1, args.repeat + 1):
            if args.repeat > 1:
                print(f"--- pass {round_index}/{args.repeat} ---")
            for index, node_id in enumerate(targets, start=1):
                report = await probe.probe_node(node_id)
                reports.append(report)
                flag = "pos" if report.positional else "NO-POS"
                raw = "" if report.positional else f"  raw={report.position!r}"
                print(
                    f"  [{index:>2}/{len(targets)}] {node_id}  "
                    f"{(report.name or '?'):<22} {(report.type_string or '?'):<20} {flag}{raw}"
                )
    except Exception as exc:  # noqa: BLE001 - surface anything to the operator
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        _write_outputs(probe, [], started, "failed")
        return 1
    finally:
        await probe.close()

    groups_seen: dict[str, list[str]] = defaultdict(list)
    for r in reports:
        for gid in r.groups:
            groups_seen[gid].append(r.node_id)

    print(summarise(reports, probe.params_shape, groups_seen))
    paths = _write_outputs(probe, reports, started, "ok")
    print("\nWrote:")
    for p in paths:
        print(f"  {p}")
    return 0


def _write_outputs(
    probe: UaiProbe, reports: list[NodeReport], started: datetime, status: str
) -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")

    inventory = {
        "status": status,
        "started": started.isoformat(),
        "host": probe.host,
        "params_shape": probe.params_shape,
        "node_count": len(reports),
        "type_histogram": dict(
            Counter((r.type_string or "<none>") for r in reports)
        ),
        "nodes": [
            {
                "node_id": r.node_id,
                "name": r.name,
                "type": r.type_string,
                "position": r.position,
                "position_error": r.position_error,
                "positional": r.positional,
                "groups": r.groups,
                "groups_error": r.groups_error,
                "info_error": r.info_error,
                "info_attempts": r.info_attempts,
            }
            for r in reports
        ],
        "notifications": probe.notifications,
        "timings": [{"method": m, "seconds": round(s, 3)} for m, s in probe.timings],
    }

    json_path = OUTPUT_DIR / f"probe-{stamp}.json"
    log_path = OUTPUT_DIR / f"probe-{stamp}.log"
    json_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    log_path.write_text("\n".join(probe.transcript.lines), encoding="utf-8")
    return [json_path, log_path]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
