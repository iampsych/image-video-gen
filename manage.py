#!/usr/bin/env python3
"""ComfyUI Deploy Manager — entry point.

    python manage.py                 # open the web UI on 127.0.0.1:8500
    python manage.py --host 0.0.0.0  # reachable from another machine on the LAN
    python manage.py --doctor        # environment check, no browser

Standard library only: this runs before ComfyUI, torch or any pip package exists.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

if sys.version_info < (3, 9):
    sys.exit(f"Python 3.9+ required, found {sys.version.split()[0]}")

for stream in (sys.stdout, sys.stderr):      # legacy Windows consoles are cp1252
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from deploy import core                      # noqa: E402
from deploy.server import serve              # noqa: E402


def print_doctor():
    cfg = core.load_config()
    report = core.doctor(cfg)
    width = max(len(c["name"]) for c in report["checks"])
    mark = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}
    print()
    for check in report["checks"]:
        print(f"  {mark[check['status']]} {check['name']:<{width}}  {check['detail']}")
        if check["hint"] and check["status"] != "ok":
            print(f"         {' ' * width}  -> {check['hint']}")
    manifest = core.manifest_state(cfg)
    have = sum(g["have"] for g in manifest["groups"])
    total = sum(g["total"] for g in manifest["groups"])
    missing = sum(g["missing_bytes"] for g in manifest["groups"])
    print(f"\n  models: {have}/{total} present — {missing/1e9:.1f} GB still to download\n")
    return 0 if all(c["status"] != "fail" for c in report["checks"]) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="ComfyUI deployment manager")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 for LAN)")
    parser.add_argument("--port", type=int, default=8500, help="manager port (default 8500)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--doctor", action="store_true", help="print the environment check and exit")
    args = parser.parse_args()

    if args.doctor:
        return print_doctor()

    if not args.no_browser:
        url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}/"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
