"""Resumable downloads and streamed subprocess tasks.

Two long-running concerns live here:

* ``Downloads`` — a small worker pool fetching model files, resuming partial
  ``.part`` files with HTTP Range requests.
* ``Task`` / ``ComfyProcess`` — subprocess wrappers that stream output into a
  ring buffer the web UI polls.
"""
from __future__ import annotations

import collections
import hashlib
import os
import queue
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHUNK = 1 << 20  # 1 MiB
USER_AGENT = "comfyui-deploy/1.0"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- downloads

class PermanentError(RuntimeError):
    """A failure retrying cannot fix — bad credentials, missing file."""


class Download:
    def __init__(self, model: dict, dest: Path):
        self.file = model["file"]
        self.folder = model["folder"]
        self.url = model["url"]
        self.source = model.get("source", "hf")   # hf | civitai
        self.size = model["size"] or 0
        self.sha256 = model.get("sha256")
        self.dest = dest
        self.key = f"{self.folder}/{self.file}"
        self.done = 0
        self.status = "queued"     # queued|running|retrying|done|error|cancelled
        self.error = ""
        self.speed = 0.0
        self.attempt = 0
        self.max_attempts = 1
        self.cancel = threading.Event()

    def complete_on_disk(self) -> bool:
        try:
            return self.dest.exists() and (not self.size or self.dest.stat().st_size == self.size)
        except OSError:
            return False

    def as_dict(self) -> dict:
        return {
            "key": self.key, "file": self.file, "folder": self.folder,
            "source": self.source, "size": self.size,
            "done": self.done, "status": self.status, "error": self.error,
            "speed": round(self.speed, 1),
            "attempt": self.attempt, "max_attempts": self.max_attempts,
            "percent": round(100 * self.done / self.size, 1) if self.size else 0,
        }


class Downloads:
    """Worker pool with resume, size verification and optional hashing."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: dict[str, Download] = {}
        self.queue: queue.Queue[Download] = queue.Queue()
        self.workers: list[threading.Thread] = []
        self.tokens = {"hf": "", "civitai": ""}
        self.verify_sha = False
        self.max_retries = 5

    # -- control ----------------------------------------------------------

    def configure(self, concurrency: int, hf_token: str, civitai_token: str, verify_sha: bool,
                  max_retries: int = 5):
        self.tokens = {"hf": hf_token or "", "civitai": civitai_token or ""}
        self.verify_sha = bool(verify_sha)
        self.max_retries = max(1, min(int(max_retries or 5), 20))
        want = max(1, min(int(concurrency or 2), 6))
        while len(self.workers) < want:
            thread = threading.Thread(target=self._worker, daemon=True)
            thread.start()
            self.workers.append(thread)

    def enqueue(self, models: list[tuple[dict, Path]]) -> int:
        added = 0
        with self.lock:
            for model, dest in models:
                job = Download(model, dest)
                existing = self.jobs.get(job.key)
                if existing and existing.status in ("queued", "running"):
                    continue
                self.jobs[job.key] = job
                self.queue.put(job)
                added += 1
        return added

    def cancel(self, key: str):
        with self.lock:
            job = self.jobs.get(key)
        if job:
            job.cancel.set()
            if job.status == "queued":
                job.status = "cancelled"

    def cancel_all(self):
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel.set()
            if job.status == "queued":
                job.status = "cancelled"

    def prune(self):
        """Forget finished jobs whose file is now correct on disk.

        Without this a stale ``cancelled`` or ``error`` job keeps shadowing a
        file that has since downloaded fine, and the UI shows the dead status
        instead of 'installed'.
        """
        with self.lock:
            for key, job in list(self.jobs.items()):
                if job.status in ("done", "cancelled", "error") and job.complete_on_disk():
                    del self.jobs[key]

    def snapshot(self) -> dict:
        self.prune()
        with self.lock:
            jobs = [j.as_dict() for j in self.jobs.values()]
        live = ("queued", "running", "retrying")
        active = [j for j in jobs if j["status"] in live]
        return {
            "jobs": jobs,
            "active": len(active),
            "total_bytes": sum(j["size"] for j in active),
            "done_bytes": sum(j["done"] for j in active),
            "speed": sum(j["speed"] for j in jobs if j["status"] == "running"),
        }

    # -- worker -----------------------------------------------------------

    def _worker(self):
        while True:
            job = self.queue.get()
            try:
                self._attempt(job)
            finally:
                self.queue.task_done()

    def _attempt(self, job: Download):
        """Run a job, retrying transient failures with exponential backoff.

        A dropped connection part-way through a 14 GB file is normal over hours
        of downloading, and every retry resumes from the ``.part`` offset, so a
        blip costs seconds rather than the whole file.
        """
        job.max_attempts = self.max_retries
        delay = 5
        for attempt in range(1, self.max_retries + 1):
            if job.cancel.is_set():
                job.status = "cancelled"
                return
            job.attempt = attempt
            try:
                self._fetch(job)
            except PermanentError as exc:
                job.status = "error"
                job.error = str(exc)
                return
            except Exception as exc:                      # noqa: BLE001 - surfaced in UI
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"

            if job.status in ("done", "cancelled"):
                return
            if attempt >= self.max_retries:
                job.error = f"{job.error} (gave up after {attempt} attempts)"
                return

            job.status = "retrying"
            job.speed = 0.0
            if job.cancel.wait(delay):                    # interruptible sleep
                job.status = "cancelled"
                return
            delay = min(delay * 2, 120)

    def _authorize(self, job: Download) -> tuple[str, dict]:
        """Attach credentials the way each host expects.

        Civitai 307s to a signed CDN URL that carries its own ``Authorization``
        query parameter, and an ``Authorization`` *header* surviving that
        redirect makes the CDN reject the request — so the token goes in the
        query string instead. HuggingFace wants a bearer header.
        """
        headers = {"User-Agent": USER_AGENT}
        token = self.tokens.get(job.source, "")
        url = job.url
        if not token:
            return url, headers
        if job.source == "civitai":
            joiner = "&" if urllib.parse.urlparse(url).query else "?"
            url = f"{url}{joiner}token={urllib.parse.quote(token)}"
        else:
            headers["Authorization"] = f"Bearer {token}"
        return url, headers

    def _fetch(self, job: Download):
        job.status = "running"
        job.error = ""
        dest = job.dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")

        if dest.exists() and job.size and dest.stat().st_size == job.size:
            job.done = job.size
            job.status = "done"
            return

        offset = part.stat().st_size if part.exists() else 0
        if job.size and offset > job.size:                # corrupt leftover
            part.unlink()
            offset = 0

        url, headers = self._authorize(job)
        if offset:
            headers["Range"] = f"bytes={offset}-"

        request = urllib.request.Request(url, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and job.size and offset == job.size:
                response = None                            # already complete
            elif exc.code in (401, 403):
                where = "Civitai" if job.source == "civitai" else "HuggingFace"
                raise PermanentError(
                    f"HTTP {exc.code} — this download needs authentication. "
                    f"Add a {where} API key in Settings.") from exc
            elif exc.code == 404:
                raise PermanentError("HTTP 404 — the file is gone from the host.") from exc
            else:
                raise

        if response is not None:
            resuming = response.status == 206
            if offset and not resuming:                    # server ignored Range
                offset = 0
            mode = "ab" if (offset and resuming) else "wb"
            job.done = offset if mode == "ab" else 0

            window_start, window_bytes = time.monotonic(), 0
            with response, open(part, mode) as handle:
                while True:
                    if job.cancel.is_set():
                        job.status = "cancelled"
                        return
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    job.done += len(chunk)
                    window_bytes += len(chunk)
                    elapsed = time.monotonic() - window_start
                    if elapsed >= 0.5:
                        job.speed = window_bytes / elapsed
                        window_start, window_bytes = time.monotonic(), 0

        actual = part.stat().st_size if part.exists() else 0
        if job.size and actual != job.size:
            if actual > job.size:              # overshoot can only be a bad .part
                part.unlink(missing_ok=True)
            # transient: the stream ended early, so retry resumes from the offset
            raise RuntimeError(f"incomplete transfer: {actual:,} of {job.size:,} bytes")

        if self.verify_sha and job.sha256:
            digest = hashlib.sha256()
            with open(part, "rb") as handle:
                for block in iter(lambda: handle.read(CHUNK), b""):
                    if job.cancel.is_set():
                        job.status = "cancelled"
                        return
                    digest.update(block)
            if digest.hexdigest() != job.sha256:
                part.unlink(missing_ok=True)   # start clean on the next attempt
                raise RuntimeError("sha256 mismatch — refetching from scratch")

        if dest.exists():
            dest.unlink()
        os.replace(part, dest)
        job.speed = 0.0
        job.status = "done"


# --------------------------------------------------------------------------- integrity

class Verifier:
    """Hash installed files against the manifest.

    A truncated download is caught by the size check, but a file that is the
    right length with wrong bytes is not — and safetensors are memory-mapped, so
    torch meets the bad bytes as a Windows page-fault (0xC0000006) that kills the
    process instead of raising. Hashing is the only way to tell the difference
    before ComfyUI tries to load the thing.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.results: dict[str, dict] = {}
        self.running = False
        self.current = ""
        self.done_bytes = 0
        self.total_bytes = 0
        self.cancel = threading.Event()

    def snapshot(self) -> dict:
        with self.lock:
            results = dict(self.results)
        bad = [k for k, v in results.items() if v["state"] == "corrupt"]
        return {
            "running": self.running, "current": self.current,
            "done_bytes": self.done_bytes, "total_bytes": self.total_bytes,
            "percent": round(100 * self.done_bytes / self.total_bytes, 1) if self.total_bytes else 0,
            "results": results, "corrupt": bad,
            "checked": len(results),
        }

    def start(self, items: list[dict]) -> bool:
        """items: [{key, path, size, sha256}]"""
        if self.running:
            return False
        self.cancel.clear()
        with self.lock:
            self.results = {}
        self.total_bytes = sum(i["size"] or 0 for i in items)
        self.done_bytes = 0
        self.running = True
        threading.Thread(target=self._run, args=(items,), daemon=True).start()
        return True

    def stop(self):
        self.cancel.set()

    def _record(self, key, state, detail=""):
        with self.lock:
            self.results[key] = {"state": state, "detail": detail}

    def _run(self, items):
        try:
            for item in items:
                if self.cancel.is_set():
                    break
                key, path = item["key"], Path(item["path"])
                self.current = key
                if not path.exists():
                    self._record(key, "missing")
                    continue
                actual_size = path.stat().st_size
                if item["size"] and actual_size != item["size"]:
                    self._record(key, "corrupt",
                                 f"size {actual_size:,} != expected {item['size']:,}")
                    self.done_bytes += item["size"] or 0
                    continue
                if not item.get("sha256"):
                    self._record(key, "no-hash", "manifest has no sha256 for this file")
                    self.done_bytes += actual_size
                    continue
                digest = hashlib.sha256()
                try:
                    with open(path, "rb") as handle:
                        for block in iter(lambda: handle.read(CHUNK), b""):
                            if self.cancel.is_set():
                                return
                            digest.update(block)
                            self.done_bytes += len(block)
                except OSError as exc:
                    # a genuinely unreadable file fails here rather than in torch
                    self._record(key, "corrupt", f"read error: {exc}")
                    continue
                if digest.hexdigest() == item["sha256"]:
                    self._record(key, "ok")
                else:
                    self._record(key, "corrupt", "sha256 mismatch - re-download this file")
        finally:
            self.running = False
            self.current = ""


# --------------------------------------------------------------------------- processes

class Task:
    """One setup step at a time (clone, venv, pip install), output streamed."""

    def __init__(self, maxlines: int = 800):
        self.lock = threading.Lock()
        self.lines: collections.deque[str] = collections.deque(maxlen=maxlines)
        self.name = ""
        self.status = "idle"        # idle|running|done|error
        self.returncode = None
        self.proc: subprocess.Popen | None = None

    def running(self) -> bool:
        return self.status == "running"

    def log(self, text: str):
        with self.lock:
            self.lines.append(text.rstrip())

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "name": self.name, "status": self.status,
                "returncode": self.returncode, "lines": list(self.lines),
            }

    def start(self, name: str, steps: list[list[str]], cwd: Path | None = None,
              env: dict | None = None) -> bool:
        if self.running():
            return False
        with self.lock:
            self.lines.clear()
            self.name = name
            self.status = "running"
            self.returncode = None
        threading.Thread(target=self._run, args=(steps, cwd, env), daemon=True).start()
        return True

    def _run(self, steps, cwd, env):
        merged = {**os.environ, **(env or {})}
        for args in steps:
            self.log(f"$ {' '.join(args)}")
            try:
                self.proc = subprocess.Popen(
                    args, cwd=str(cwd) if cwd else None, env=merged,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, encoding="utf-8", errors="replace",
                    creationflags=NO_WINDOW,
                )
            except OSError as exc:
                self.log(f"!! failed to launch: {exc}")
                self.status = "error"
                self.returncode = -1
                return
            for line in self.proc.stdout:                  # type: ignore[union-attr]
                self.log(line)
            code = self.proc.wait()
            self.returncode = code
            if code != 0:
                self.log(f"!! exited with code {code}")
                self.status = "error"
                return
        self.log("-- finished --")
        self.status = "done"

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class ComfyProcess:
    """The ComfyUI server itself — long lived, restartable."""

    def __init__(self, maxlines: int = 500):
        self.lock = threading.Lock()
        self.lines: collections.deque[str] = collections.deque(maxlen=maxlines)
        self.proc: subprocess.Popen | None = None
        self.url = ""

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def snapshot(self) -> dict:
        with self.lock:
            lines = list(self.lines)
        return {"running": self.alive(), "url": self.url if self.alive() else "", "lines": lines}

    def start(self, python: Path, cwd: Path, listen: str, port: int, extra: str) -> str:
        if self.alive():
            return "already running"
        if not python.exists():
            return f"python not found: {python}"
        args = [str(python), "main.py", "--port", str(port)]
        if listen and listen not in ("127.0.0.1", "localhost"):
            args += ["--listen", listen]
        args += shlex.split(extra or "")
        with self.lock:
            self.lines.clear()
            self.lines.append(f"$ {' '.join(args)}")
        try:
            self.proc = subprocess.Popen(
                args, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            return f"failed to launch: {exc}"
        host = listen if listen not in ("0.0.0.0", "") else "127.0.0.1"
        self.url = f"http://{host}:{port}/"
        threading.Thread(target=self._pump, daemon=True).start()
        return ""

    def _pump(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip())
        with self.lock:
            self.lines.append("-- ComfyUI exited --")

    def stop(self):
        if self.alive():
            self.proc.terminate()                          # type: ignore[union-attr]
            try:
                self.proc.wait(timeout=15)                 # type: ignore[union-attr]
            except subprocess.TimeoutExpired:
                self.proc.kill()                           # type: ignore[union-attr]
