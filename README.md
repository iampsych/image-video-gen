# ComfyUI Deploy

A small, dependency-free manager for standing up a ComfyUI box for **Flux image
generation** and **WAN 2.1 / 2.2 video generation**.

Clone this repo on the target machine, run one command, and drive the rest from a
web UI: clone ComfyUI, build the venv, install the correct PyTorch for the GPU,
download ~148 GB of models with resume, install workflows, and launch the server.

The manager itself is **standard library Python only** — it has to run before
ComfyUI, torch, or any pip package exists.

---

## Quick start

```powershell
git clone https://github.com/iampsych/image-video-gen.git
cd image-video-gen
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

The UI opens at <http://127.0.0.1:8500>. To drive it from another machine:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -BindHost 0.0.0.0
```

Cross-platform equivalent:

```bash
python manage.py                 # local
python manage.py --host 0.0.0.0  # LAN
python manage.py --doctor        # environment check, no server
```

Requires **Python 3.9+** and **git** on PATH.

---

## Order of operations on a fresh machine

1. **Status** — confirm the GPU is visible and note what's failing.
2. **Settings** — set the ComfyUI directory, the models directory, and the
   PyTorch channel. **RTX 50-series must use `cu128`.**
3. **Setup** — run the four steps top to bottom.
4. **Models** — *Select recommended*, then *Download*. Resume is automatic.
5. **Workflows** — *Install workflows*.
6. **Launch** — start ComfyUI and open it.

---

## The RTX 5090 gotcha

Blackwell cards report compute capability **sm_120**. PyTorch builds before
**2.7** — including the common `2.6.0+cu124` — ship no sm_120 kernels and fail at
the first CUDA operation, usually with `no kernel image is available for
execution on the device`.

Use the **`cu128`** channel (CUDA 12.8). The Status tab checks this explicitly:
it reads the card's actual compute capability and the installed torch version,
and fails the *GPU visible to torch* check with the fix if they don't match.

A venv is never portable between machines — always rebuild it on the target.

---

## What gets downloaded

Sizes and SHA-256 digests in `models.manifest.json` were fetched from the
HuggingFace API, and the filenames match the workflow templates that ship with
ComfyUI, so the graphs load without touching a dropdown.

| Group | Size | What it's for |
|---|---:|---|
| `flux` | 34.2 GB | Flux.1-dev still images |
| `wan21_core` | 21.3 GB | WAN 2.1 text-to-video + shared UMT5 encoder and VAE |
| `wan21_i2v` | 17.7 GB | WAN 2.1 image-to-video (+ `clip_vision_h`) |
| `wan21_speed` | 1.4 GB | lightx2v step-distill LoRAs for 2.1 |
| `wan22_t2v` | 31.0 GB | WAN 2.2 text-to-video, 14B two-expert MoE + 4-step LoRAs |
| `wan22_i2v` | 31.0 GB | WAN 2.2 image-to-video, 14B MoE + 4-step LoRAs |
| `wan22_5b` | 11.4 GB | WAN 2.2 TI2V 5B — faster and lighter, lower fidelity (optional) |

**148 GB total.** Everything resolves without authentication; the HF token field
in Settings is only there for licence-gated repositories.

Notes worth knowing:

- WAN 2.2 14B is a **mixture-of-experts pair** — the high-noise and low-noise
  models both load, and both need their matching LoRA half.
- The WAN 2.2 **14B** models reuse `wan_2.1_vae`. Only the **5B** model needs
  `wan2.2_vae`.
- The **lightx2v LoRAs are the single biggest speedup** — roughly 20 steps down
  to 4-6.

## Bundled workflows

Copied into `ComfyUI/user/default/workflows/` by the Workflows tab:

| File | Notes |
|---|---|
| `flux_text_to_image.json` | The graph already proven working on the 4090 |
| `wan2.1_text_to_video_14B.json` | Repointed from the 1.3B default to the 14B model |
| `wan2.1_image_to_video_720p.json` | Repointed from the 480p default to 720p fp8 |
| `wan2.2_text_to_video_14B.json` | Official template, unmodified |
| `wan2.2_image_to_video_14B.json` | Official template, unmodified |
| `wan2.2_ti2v_5B.json` | Official template, unmodified |

---

## Layout

```
manage.py               entry point (--doctor, --host, --port)
deploy/core.py          config, manifest state, environment probing
deploy/jobs.py          resumable downloader + streamed subprocess tasks
deploy/server.py        stdlib HTTP server and JSON API
deploy/static/          the single-page UI
models.manifest.json    verified URLs, exact sizes, SHA-256
workflows/              graphs installed into ComfyUI
scripts/bootstrap.ps1   preflight + launch for Windows
config.json             local settings — gitignored, never committed
```

`config.json` holds machine-specific paths and your HF token, so it stays out of
git. Every machine gets its own.

### Sharing one model library

Point **Models directory** at a network share or second drive to avoid
re-downloading 148 GB per machine. The manager reads and writes only that path;
ComfyUI picks models up from wherever it's told.

---

## Reference

`python manage.py --doctor` prints the same checks as the Status tab and exits
non-zero if any fail — useful over SSH or in a scheduled task.

API, if you want to script it:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/state` | Everything: config, checks, manifest state, jobs |
| `POST` | `/api/config` | Patch settings |
| `POST` | `/api/download` | `{"groups":[...]}` or `{"files":[...]}` |
| `POST` | `/api/download/cancel` | `{"all":true}` or `{"file":"..."}` |
| `POST` | `/api/setup` | `{"step":"clone\|venv\|torch\|requirements"}` |
| `POST` | `/api/workflows/install` | Copy workflows into ComfyUI |
| `POST` | `/api/comfy/start` · `/api/comfy/stop` | Control the ComfyUI process |

The manager binds to `127.0.0.1` by default. It has **no authentication** — it
can run arbitrary setup commands, so only expose it on a network you trust.
