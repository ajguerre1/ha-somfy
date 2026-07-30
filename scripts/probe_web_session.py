#!/usr/bin/env python3
"""Can a pilot.htm session unlock the 403 endpoints? (PROTO-07, reopened)

`pilot.htm` authenticates with `GET /password.cgi?VERIFY=<password>` and treats
HTTP 200 as success. If that establishes a session, `somfy_devices.json` and
`somfy_presets.json` may become readable.

Read-only. The only parameter sent to password.cgi is VERIFY, which checks a
password; nothing here sets or changes one, and no motor command is issued.

    python scripts/probe_web_session.py
"""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS_FILE = Path(__file__).resolve().parent / "secrets.local.json"
TIMEOUT = 15
SAMPLE_NODE = "13.6E.A5"

GATED = ["somfy_devices.json", f"somfy_presets.json?{SAMPLE_NODE}"]


def make_opener() -> urllib.request.OpenerDirector:
    """An opener with a cookie jar, so any session cookie is carried forward."""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def get(opener, url: str) -> tuple[int, str]:
    try:
        with opener.open(url, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.reason or ""
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return 0, str(err)


def main() -> int:
    secrets = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    host = secrets["host"]
    web_password = secrets.get("web_password")
    if not web_password:
        print("No 'web_password' in secrets.local.json", file=sys.stderr)
        return 2

    opener, jar = make_opener()
    base = f"http://{host}"

    print("=== before login ===")
    for path in GATED:
        status, body = get(opener, f"{base}/{path}")
        print(f"  {path:<34} -> HTTP {status}  {body[:80]!r}")

    print()
    print("=== login: GET /password.cgi?VERIFY=... ===")
    # Try the raw form the page's own JavaScript sends, then a percent-encoded
    # one, since the page does not encode the value itself.
    for label, encoded in (
        ("raw", web_password),
        ("percent-encoded", urllib.parse.quote(web_password, safe="")),
    ):
        status, body = get(opener, f"{base}/password.cgi?VERIFY={encoded}")
        cookies = [f"{c.name}={c.value}" for c in jar]
        print(f"  {label:<16} -> HTTP {status}  body={body[:60]!r}  cookies={cookies}")
        if status == 200:
            break

    print()
    print("=== after login ===")
    for path in GATED:
        status, body = get(opener, f"{base}/{path}")
        print(f"  {path:<34} -> HTTP {status}")
        if status == 200:
            print(f"      {body[:600]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
