"""Stdlib HTTP server exposing the JSON API and the single-page UI."""
from __future__ import annotations

import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import civitai, core
from .jobs import ComfyProcess, Downloads, Task

STATIC = Path(__file__).resolve().parent / "static"
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json"}

downloads = Downloads()
task = Task()
comfy = ComfyProcess()


# --------------------------------------------------------------------------- actions

def setup_steps(cfg: dict, step: str) -> tuple[str, list[list[str]], Path | None]:
    """Return (label, commands, cwd) for a setup step."""
    cdir = core.comfy_dir(cfg)
    python = core.venv_python(cfg)
    channel = cfg.get("torch_channel", "cu128")

    if step == "clone":
        cdir.parent.mkdir(parents=True, exist_ok=True)
        if (cdir / "main.py").exists():
            return "Update ComfyUI", [["git", "pull", "--ff-only"]], cdir
        return "Clone ComfyUI", [["git", "clone", core.COMFY_REPO, str(cdir)]], cdir.parent

    if step == "venv":
        return "Create virtual environment", [[sys.executable, "-m", "venv", str(cdir / "venv")]], cdir

    if step == "torch":
        index = f"https://download.pytorch.org/whl/{channel}"
        return (f"Install PyTorch ({channel})", [
            [str(python), "-m", "pip", "install", "--upgrade", "pip"],
            [str(python), "-m", "pip", "install", "--upgrade", "--force-reinstall",
             "torch", "torchvision", "torchaudio", "--index-url", index],
        ], cdir)

    if step == "requirements":
        return "Install ComfyUI requirements", [
            [str(python), "-m", "pip", "install", "-r", str(cdir / "requirements.txt")],
        ], cdir

    raise KeyError(step)


def install_workflows(cfg: dict) -> dict:
    """Copy the bundled workflows into the ComfyUI user directory."""
    dest = core.comfy_dir(cfg) / "user" / "default" / "workflows"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sorted(core.WORKFLOW_DIR.glob("*.json")):
        shutil.copy2(src, dest / src.name)
        copied.append(src.name)
    return {"copied": copied, "dest": str(dest)}


def configure_downloads(cfg: dict):
    downloads.configure(cfg.get("concurrency", 2), cfg.get("hf_token", ""),
                        cfg.get("civitai_token", ""), cfg.get("verify_sha256", False),
                        cfg.get("max_retries", 5))


def state() -> dict:
    cfg = core.load_config()
    return {
        "config": cfg,
        "doctor": core.doctor(cfg),
        "manifest": core.manifest_state(cfg),
        "civitai": civitai.saved_state(cfg),
        "downloads": downloads.snapshot(),
        "task": task.snapshot(),
        "comfy": comfy.snapshot(),
        "paths": {"models": str(core.models_dir(cfg)), "comfyui": str(core.comfy_dir(cfg))},
    }


# --------------------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "comfyui-deploy"

    def log_message(self, fmt, *args):                     # quieter console
        pass

    # -- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code: int = 200):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _static(self, path: str):
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / name).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        if self.path.startswith("/api/state"):
            self._json(state())
        elif self.path.startswith("/api/"):
            self._json({"error": "unknown endpoint"}, 404)
        else:
            self._static(self.path.split("?")[0])

    def do_POST(self):
        route = self.path.split("?")[0]
        body = self._body()
        cfg = core.load_config()

        try:
            if route == "/api/config":
                cfg = core.save_config(body)
                self._json({"ok": True, "config": cfg})

            elif route == "/api/download":
                manifest = core.manifest_state(cfg)
                wanted_groups = set(body.get("groups") or [])
                wanted_files = set(body.get("files") or [])
                selected = []
                for group in manifest["groups"]:
                    for model in group["models"]:
                        chosen = group["id"] in wanted_groups or model["file"] in wanted_files
                        if chosen and model["state"] != "ok":
                            selected.append((model, core.target_path(cfg, model)))
                configure_downloads(cfg)
                self._json({"ok": True, "queued": downloads.enqueue(selected)})

            elif route == "/api/download/cancel":
                if body.get("all"):
                    downloads.cancel_all()
                else:
                    downloads.cancel(body.get("key", ""))
                self._json({"ok": True})

            elif route == "/api/civitai/resolve":
                try:
                    self._json({"ok": True,
                                "model": civitai.resolve(body.get("ref", ""),
                                                         cfg.get("civitai_token", ""))})
                except civitai.CivitaiError as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)

            elif route == "/api/civitai/add":
                try:
                    resolved = civitai.resolve(body.get("ref", ""), cfg.get("civitai_token", ""))
                    record = civitai.add(resolved, int(body["version_id"]),
                                         int(body["file_id"]), body.get("folder", ""))
                    self._json({"ok": True, "record": record})
                except (civitai.CivitaiError, KeyError, ValueError) as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)

            elif route == "/api/civitai/remove":
                self._json({"ok": civitai.remove(body.get("key", ""))})

            elif route == "/api/civitai/download":
                saved = civitai.saved_state(cfg)
                keys = set(body.get("keys") or [])
                selected = []
                for record in saved["models"]:
                    if record["state"] == "ok":
                        continue
                    if body.get("all") or record["key"] in keys:
                        selected.append(({**record, "source": "civitai"},
                                         civitai.download_target(cfg, record)))
                configure_downloads(cfg)
                self._json({"ok": True, "queued": downloads.enqueue(selected)})

            elif route == "/api/setup":
                step = body.get("step", "")
                try:
                    label, steps, cwd = setup_steps(cfg, step)
                except KeyError:
                    self._json({"ok": False, "error": f"unknown step '{step}'"}, 400)
                    return
                started = task.start(label, steps, cwd)
                self._json({"ok": started,
                            "error": "" if started else "another task is already running"})

            elif route == "/api/workflows/install":
                self._json({"ok": True, **install_workflows(cfg)})

            elif route == "/api/comfy/start":
                error = comfy.start(core.venv_python(cfg), core.comfy_dir(cfg),
                                    cfg.get("listen", "127.0.0.1"), int(cfg.get("port", 8188)),
                                    cfg.get("extra_args", ""))
                self._json({"ok": not error, "error": error, "url": comfy.url})

            elif route == "/api/comfy/stop":
                comfy.stop()
                self._json({"ok": True})

            elif route == "/api/shutdown":
                self._json({"ok": True})
                os._exit(0)

            else:
                self._json({"error": "unknown endpoint"}, 404)

        except Exception as exc:                            # noqa: BLE001 - report to UI
            self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)


def serve(host: str, port: int):
    configure_downloads(core.load_config())
    httpd = ThreadingHTTPServer((host, port), Handler)
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"\n  ComfyUI Deploy Manager  ->  http://{shown}:{port}/\n")
    print("  Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  shutting down...")
    finally:
        comfy.stop()
        httpd.server_close()
