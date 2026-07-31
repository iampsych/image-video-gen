"""Civitai integration — resolve a model page into concrete downloadable files.

The saved list lives in ``civitai.models.json`` and **is committed**, so pushing
from one machine and pulling on another carries the whole LoRA/checkpoint set
with it. Only the API token is machine-local (it lives in ``config.json``).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import core

SAVED_PATH = core.ROOT / "civitai.models.json"
API = "https://civitai.com/api/v1"
UA = {"User-Agent": "comfyui-deploy/1.0"}

# Civitai model type -> ComfyUI models/ subfolder
FOLDER_BY_TYPE = {
    "Checkpoint": "checkpoints",
    "LORA": "loras",
    "LoCon": "loras",
    "DoRA": "loras",
    "TextualInversion": "embeddings",
    "VAE": "vae",
    "Controlnet": "controlnet",
    "Upscaler": "upscale_models",
    "Hypernetwork": "hypernetworks",
    "MotionModule": "diffusion_models",
    "AestheticGradient": "embeddings",
}
FALLBACK_FOLDER = "loras"

# Folders the UI offers, so a user can override a bad guess
FOLDERS = ["loras", "checkpoints", "diffusion_models", "embeddings", "vae",
           "controlnet", "upscale_models", "hypernetworks", "clip_vision", "text_encoders"]


class CivitaiError(RuntimeError):
    pass


# --------------------------------------------------------------------------- refs

def parse_ref(text: str) -> dict:
    """Accept a model page URL, a download URL, or a bare id."""
    text = (text or "").strip()
    if not text:
        raise CivitaiError("Paste a Civitai model URL or id.")

    # https://civitai.com/api/download/models/<versionId>
    match = re.search(r"/api/download/models/(\d+)", text)
    if match:
        return {"version_id": int(match.group(1))}

    version_id = None
    query = re.search(r"[?&]modelVersionId=(\d+)", text)
    if query:
        version_id = int(query.group(1))

    # https://civitai.com/models/<modelId>/<slug>
    match = re.search(r"/models/(\d+)", text)
    if match:
        return {"model_id": int(match.group(1)), "version_id": version_id}

    # a bare id, optionally carrying a ?modelVersionId= query
    match = re.match(r"^(\d+)", text)
    if match:
        return {"model_id": int(match.group(1)), "version_id": version_id}

    raise CivitaiError("Could not find a model id in that. Paste the full Civitai URL.")


# --------------------------------------------------------------------------- api

def _get(url: str, token: str = "") -> dict:
    headers = dict(UA)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise CivitaiError("Not found on Civitai — check the id.") from exc
        if exc.code in (401, 403):
            raise CivitaiError("Civitai refused the request. Add an API key in Settings.") from exc
        raise CivitaiError(f"Civitai returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CivitaiError(f"Could not reach Civitai: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CivitaiError("Civitai returned something that isn't JSON.") from exc


def _norm_file(entry: dict) -> dict:
    hashes = entry.get("hashes") or {}
    size_kb = entry.get("sizeKB") or 0
    return {
        "file_id": entry.get("id"),
        "name": entry.get("name") or "",
        "size": int(round(size_kb * 1024)),
        "sha256": (hashes.get("SHA256") or "").lower() or None,
        "kind": entry.get("type") or "Model",           # Model / VAE / Config / Training Data
        "primary": bool(entry.get("primary")),
        "url": entry.get("downloadUrl") or "",
        "scan": entry.get("virusScanResult") or "Unknown",
    }


def _norm_version(version: dict, model: dict) -> dict:
    files = [_norm_file(f) for f in (version.get("files") or [])]
    files = [f for f in files if f["url"] and f["name"]]
    files.sort(key=lambda f: (not f["primary"], f["kind"] != "Model", f["name"]))
    return {
        "version_id": version.get("id"),
        "version_name": version.get("name") or "",
        "base_model": version.get("baseModel") or "",
        "published": (version.get("publishedAt") or "")[:10],
        "files": files,
        "model_id": model.get("id"),
        "model_name": model.get("name") or "",
        "type": model.get("type") or "",
    }


def resolve(ref: str, token: str = "") -> dict:
    """Turn a user-pasted reference into model metadata plus every version/file."""
    parsed = parse_ref(ref)
    model_id, version_id = parsed.get("model_id"), parsed.get("version_id")

    if model_id is None:
        version = _get(f"{API}/model-versions/{version_id}", token)
        model_id = version.get("modelId")
        if not model_id:
            raise CivitaiError("That version has no parent model.")

    model = _get(f"{API}/models/{model_id}", token)
    versions = [_norm_version(v, model) for v in (model.get("modelVersions") or [])]
    if not versions:
        raise CivitaiError("That model has no downloadable versions.")
    if version_id:                                       # float the requested one to the top
        versions.sort(key=lambda v: v["version_id"] != version_id)

    kind = model.get("type") or ""
    return {
        "model_id": model_id,
        "name": model.get("name") or "",
        "type": kind,
        "nsfw": bool(model.get("nsfw")),
        "creator": (model.get("creator") or {}).get("username") or "",
        "page": f"https://civitai.com/models/{model_id}",
        "suggested_folder": FOLDER_BY_TYPE.get(kind, FALLBACK_FOLDER),
        "selected_version": version_id or versions[0]["version_id"],
        "versions": versions,
    }


# --------------------------------------------------------------------------- saved list

def load_saved() -> dict:
    if not SAVED_PATH.exists():
        return {"schema": 1, "models": []}
    try:
        data = json.loads(SAVED_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema": 1, "models": []}
    data.setdefault("models", [])
    return data


def _write(data: dict):
    SAVED_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def entry_key(version_id: int, file_id: int) -> str:
    return f"{version_id}:{file_id}"


def add(resolved: dict, version_id: int, file_id: int, folder: str) -> dict:
    version = next((v for v in resolved["versions"] if v["version_id"] == version_id), None)
    if version is None:
        raise CivitaiError("That version is not part of this model.")
    file = next((f for f in version["files"] if f["file_id"] == file_id), None)
    if file is None:
        raise CivitaiError("That file is not part of this version.")
    if folder not in FOLDERS:
        folder = resolved.get("suggested_folder", FALLBACK_FOLDER)

    record = {
        "key": entry_key(version_id, file_id),
        "name": resolved["name"],
        "type": resolved["type"],
        "creator": resolved.get("creator", ""),
        "model_id": resolved["model_id"],
        "version_id": version_id,
        "version_name": version["version_name"],
        "base_model": version["base_model"],
        "file_id": file_id,
        "file": file["name"],
        "folder": folder,
        "size": file["size"],
        "sha256": file["sha256"],
        "url": file["url"],
        "page": f"https://civitai.com/models/{resolved['model_id']}?modelVersionId={version_id}",
    }

    data = load_saved()
    data["models"] = [m for m in data["models"] if m.get("key") != record["key"]]
    data["models"].append(record)
    data["models"].sort(key=lambda m: (m.get("folder", ""), m.get("name", "").lower()))
    _write(data)
    return record


def remove(key: str) -> bool:
    data = load_saved()
    before = len(data["models"])
    data["models"] = [m for m in data["models"] if m.get("key") != key]
    if len(data["models"]) == before:
        return False
    _write(data)
    return True


def saved_state(cfg: dict) -> dict:
    """The saved list annotated with on-disk status, same vocabulary as the manifest."""
    data = load_saved()
    models = []
    for record in data["models"]:
        path = core.models_dir(cfg) / record["folder"] / record["file"]
        part = path.with_suffix(path.suffix + ".part")
        item = dict(record)
        if path.exists():
            actual = path.stat().st_size
            item["state"] = "ok" if (not record["size"] or actual == record["size"]) else "size-mismatch"
            item["local_size"] = actual
        elif part.exists():
            item["state"] = "partial"
            item["local_size"] = part.stat().st_size
        else:
            item["state"] = "missing"
            item["local_size"] = 0
        models.append(item)
    missing = [m for m in models if m["state"] != "ok"]
    return {
        "models": models,
        "have": len(models) - len(missing),
        "total": len(models),
        "missing_bytes": sum(m["size"] - m["local_size"] for m in missing),
        "folders": FOLDERS,
    }


def download_target(cfg: dict, record: dict) -> Path:
    return core.models_dir(cfg) / record["folder"] / record["file"]
