"""Configuration, manifest handling and environment probing.

Everything here is standard library only, so the manager runs on a bare machine
before ComfyUI or torch exist.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
MANIFEST_PATH = ROOT / "models.manifest.json"
WORKFLOW_DIR = ROOT / "workflows"

COMFY_REPO = "https://github.com/comfyanonymous/ComfyUI.git"

# Blackwell (RTX 50-series) is compute capability 12.0 and needs CUDA 12.8+.
BLACKWELL_MAJOR = 12
MIN_TORCH_FOR_BLACKWELL = (2, 7)

DEFAULTS = {
    "comfyui_dir": str(ROOT.parent / "ComfyUI"),
    "models_dir": "",            # blank -> <comfyui_dir>/models
    "torch_channel": "cu128",    # cu128 = CUDA 12.8, required for RTX 50-series
    "listen": "127.0.0.1",
    "port": 8188,
    "extra_args": "",
    "hf_token": "",              # only needed for licence-gated repos
    "concurrency": 2,
    "verify_sha256": False,      # full hashing of 20 GB files is slow; size check is default
}


# --------------------------------------------------------------------------- config

def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(patch: dict) -> dict:
    cfg = load_config()
    for key, value in patch.items():
        if key in DEFAULTS:
            cfg[key] = value
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def comfy_dir(cfg: dict) -> Path:
    return Path(cfg["comfyui_dir"]).expanduser()


def models_dir(cfg: dict) -> Path:
    return Path(cfg["models_dir"]).expanduser() if cfg.get("models_dir") else comfy_dir(cfg) / "models"


def venv_python(cfg: dict) -> Path:
    base = comfy_dir(cfg) / "venv"
    return base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# --------------------------------------------------------------------------- manifest

def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def target_path(cfg: dict, model: dict) -> Path:
    return models_dir(cfg) / model["folder"] / model["file"]


def manifest_state(cfg: dict) -> dict:
    """Annotate the manifest with on-disk status for each file."""
    manifest = load_manifest()
    for group in manifest["groups"]:
        have = 0
        for model in group["models"]:
            path = target_path(cfg, model)
            part = path.with_suffix(path.suffix + ".part")
            if path.exists():
                actual = path.stat().st_size
                model["state"] = "ok" if actual == model["size"] else "size-mismatch"
                model["local_size"] = actual
            elif part.exists():
                model["state"] = "partial"
                model["local_size"] = part.stat().st_size
            else:
                model["state"] = "missing"
                model["local_size"] = 0
            if model["state"] == "ok":
                have += 1
        group["have"] = have
        group["total"] = len(group["models"])
        group["missing_bytes"] = sum(
            m["size"] - m["local_size"] for m in group["models"] if m["state"] != "ok"
        )
    return manifest


# --------------------------------------------------------------------------- environment

def _run(args, timeout=25):
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


PROBE = (
    "import json,torch;"
    "d=torch.cuda.is_available();"
    "print(json.dumps({"
    "'torch':torch.__version__,"
    "'cuda':torch.version.cuda,"
    "'available':d,"
    "'device':torch.cuda.get_device_name(0) if d else None,"
    "'capability':list(torch.cuda.get_device_capability(0)) if d else None,"
    "'vram':torch.cuda.get_device_properties(0).total_memory if d else 0}))"
)


def probe_torch(cfg: dict) -> dict:
    """Ask the ComfyUI venv what torch and GPU it actually sees."""
    python = venv_python(cfg)
    if not python.exists():
        return {"present": False, "reason": "venv not created yet"}
    code, out, err = _run([str(python), "-c", PROBE], timeout=90)
    if code != 0:
        return {"present": False, "reason": (err or out or "torch import failed")[-400:]}
    try:
        info = json.loads(out.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"present": False, "reason": "could not parse torch probe output"}
    info["present"] = True
    return info


def torch_tuple(version: str) -> tuple:
    parts = []
    for chunk in version.split("+")[0].split(".")[:2]:
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def nvidia_smi() -> list:
    code, out, _ = _run([
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if code != 0:
        return []
    gpus = []
    for line in out.splitlines():
        bits = [b.strip() for b in line.split(",")]
        if len(bits) >= 3:
            gpus.append({"name": bits[0], "driver": bits[1], "vram_mb": bits[2]})
    return gpus


def doctor(cfg: dict) -> dict:
    """Produce the checklist the Status tab renders."""
    checks = []
    cdir = comfy_dir(cfg)
    mdir = models_dir(cfg)

    def add(name, ok, detail, hint=""):
        checks.append({
            "name": name,
            "status": "ok" if ok is True else ("warn" if ok is None else "fail"),
            "detail": detail, "hint": hint,
        })

    add("Manager Python", sys.version_info >= (3, 9),
        f"{platform.python_version()} ({platform.system()} {platform.release()})",
        "Python 3.9+ required to run this manager.")

    add("git available", shutil.which("git") is not None,
        shutil.which("git") or "not found on PATH",
        "Install Git so ComfyUI can be cloned and updated.")

    gpus = nvidia_smi()
    if gpus:
        gpu = gpus[0]
        add("GPU", True, f"{gpu['name']} — {int(gpu['vram_mb'])/1024:.0f} GB, driver {gpu['driver']}")
    else:
        add("GPU", False, "nvidia-smi returned nothing",
            "No NVIDIA driver detected. Generation will fall back to CPU, which is unusably slow.")

    has_comfy = (cdir / "main.py").exists()
    add("ComfyUI checkout", has_comfy,
        str(cdir) if has_comfy else f"{cdir} (main.py not found)",
        "Run Setup -> Clone ComfyUI.")

    python = venv_python(cfg)
    add("Virtual environment", python.exists(),
        str(python) if python.exists() else "not created",
        "Run Setup -> Create venv.")

    torch_info = probe_torch(cfg)
    if not torch_info.get("present"):
        add("PyTorch", False, torch_info.get("reason", "not installed"),
            "Run Setup -> Install PyTorch.")
    else:
        version = torch_info["torch"]
        add("PyTorch", True, f"{version} (CUDA {torch_info.get('cuda')})")
        if torch_info.get("available"):
            cap = torch_info.get("capability") or [0, 0]
            name = torch_info.get("device")
            vram = torch_info.get("vram", 0) / 1e9
            blackwell = cap[0] >= BLACKWELL_MAJOR
            compatible = (not blackwell) or torch_tuple(version) >= MIN_TORCH_FOR_BLACKWELL
            add("GPU visible to torch", compatible,
                f"{name} — sm_{cap[0]}{cap[1]}, {vram:.0f} GB VRAM",
                "" if compatible else
                f"torch {version} has no sm_{cap[0]}{cap[1]} kernels. RTX 50-series needs "
                f"torch >= 2.7 built for CUDA 12.8. Reinstall PyTorch with channel cu128.")
        else:
            add("GPU visible to torch", False, "torch.cuda.is_available() is False",
                "Reinstall PyTorch for the correct CUDA channel.")

    try:
        usage = shutil.disk_usage(mdir if mdir.exists() else mdir.anchor or cdir.anchor)
        free_gb = usage.free / 1e9
        add("Disk space", free_gb > 60 or None, f"{free_gb:.0f} GB free at {mdir.anchor or mdir}",
            "" if free_gb > 60 else "The full model set is ~148 GB. Free up space or pick fewer groups.")
    except OSError as exc:
        add("Disk space", None, f"could not read: {exc}")

    return {"checks": checks, "torch": torch_info, "gpus": gpus}
