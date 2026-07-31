# ComfyUI Deploy

A small, dependency-free manager for standing up a ComfyUI box for **Flux image
generation** and **WAN 2.1 / 2.2 video generation**.

Clone this repo on the target machine, run one command, and drive everything else
from a web UI: clone ComfyUI, build the venv, install the correct PyTorch for the
GPU, download ~148 GB of models with resume, install workflows, launch the server.

The manager itself is **standard library Python only**. That is deliberate — it
has to run on a bare machine *before* ComfyUI, torch, or any pip package exists.
Adding a third-party dependency to the manager would break the bootstrap.

---

## Contents

- [Quick start](#quick-start)
- [First run, step by step](#first-run-step-by-step)
- [What each tab does](#what-each-tab-does)
- [The RTX 5090 gotcha](#the-rtx-5090-gotcha)
- [What gets downloaded](#what-gets-downloaded)
- [Civitai LoRAs and checkpoints](#civitai-loras-and-checkpoints)
- [Bundled workflows](#bundled-workflows)
- [Running it from another machine](#running-it-from-another-machine)
- [Sharing one model library](#sharing-one-model-library)
- [Troubleshooting](#troubleshooting)
- [Command line](#command-line)
- [HTTP API](#http-api)
- [Repo layout](#repo-layout)
- [Security](#security)

---

## Quick start

On the target machine (Windows):

```powershell
git clone https://github.com/iampsych/image-video-gen.git
cd image-video-gen
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

The UI opens at <http://127.0.0.1:8500>.

Cross-platform equivalent, or if you'd rather skip the PowerShell wrapper:

```bash
python manage.py                 # local only
python manage.py --host 0.0.0.0  # reachable across the LAN
python manage.py --doctor        # environment check, no server, no browser
```

**Prerequisites:** Python 3.9+ and git on PATH. Nothing else — no pip install
step. `bootstrap.ps1` checks both and tells you what's missing before starting.

### Which Python

**3.10 or newer. Anything current works, including 3.14.**

All 35 packages in ComfyUI's `requirements.txt` have working wheels on 3.14 —
`tokenizers` and `safetensors` cover it through forward-compatible `cp310-abi3`
builds rather than a literal `cp314` tag, which is easy to misread as missing
support. On 3.14, pip resolves torch to 2.9 or newer, since that's where cu128
`cp314` wheels start. That's comfortably above the 2.7 the RTX 50-series needs.

Two interpreters are involved and they don't have to match:

- **The one running the manager** — anything 3.9+. Standard library only.
- **The one inside ComfyUI's venv** — needs 3.10+. Built with whatever Python
  started the manager, unless you override it in **Settings → Python for the
  venv**.

The one caveat is **third-party custom nodes**, not ComfyUI itself. They pull
their own compiled dependencies (`insightface`, `onnxruntime`, `xformers` and
friends), and those do lag new Python releases. If you plan to lean heavily on
custom nodes, 3.12 remains the most-trodden path; if you're running stock ComfyUI
with the models in this repo, use whatever you have.

The Status tab reports the venv's Python version, fails below 3.10, and notes the
custom-node caveat above 3.12.

To change an existing venv: set **Python for the venv**, delete the `venv` folder
inside your ComfyUI directory, and re-run Setup steps 2-4. Models live in
`models/` and are untouched.

---

## First run, step by step

Work the tabs left to right. The whole thing is roughly: point it at a folder,
run four setup steps, download models, launch.

### 1. Status

Look at the checklist first. On a fresh machine most of it will be red — that's
expected. Every failing check names its own fix. The two that matter before you
go further are **GPU** (is the NVIDIA driver there at all) and **git available**.

### 2. Settings

Set these before running anything:

| Field | What to put |
|---|---|
| **ComfyUI directory** | Where ComfyUI gets cloned, e.g. `D:\ComfyUI`. Created if absent. |
| **Models directory** | Leave blank for `<ComfyUI>/models`, or point at a big drive / network share. |
| **Python for the venv** | Blank uses whatever Python is running the manager. Only set it to pick a different interpreter — 3.10+ all work, see [Which Python](#which-python). |
| **PyTorch channel** | **`cu128` for an RTX 50-series card.** See [the gotcha](#the-rtx-5090-gotcha). |
| **Bind address** | `127.0.0.1` unless you want ComfyUI reachable from another machine — then `0.0.0.0`. |
| **Port** | ComfyUI's port, default `8188`. Not the manager's port. |

Click **Save**. Leave the HF token blank — nothing in the default manifest needs
it.

### 3. Setup

Run the four steps **top to bottom**, waiting for each to finish. Output streams
into the panel underneath; the buttons disable while a step is running.

1. **Clone ComfyUI** — clones it, or fast-forwards if it's already there.
2. **Create virtual environment** — makes `venv/` inside the ComfyUI folder.
3. **Install PyTorch** — uses the channel from Settings. Big download, several minutes.
4. **Install ComfyUI requirements** — everything else from `requirements.txt`.

Then go back to **Status**. Everything should be green now, in particular *GPU
visible to torch*. If it isn't, stop and fix it here — nothing downstream will
work.

### 4. Models

Click **Select recommended**, then **Download**. That's 136.6 GB and will take a
while.

If you want less, expand the groups and pick individual files — the table in
[What gets downloaded](#what-gets-downloaded) says what each group buys you. The
minimum useful sets are:

- **Images only:** `flux` (34.2 GB)
- **Video only:** `wan21_core` + `wan21_speed` (22.7 GB)

Downloads **resume**, and transient failures **retry on their own** — up to five
attempts per file with exponential backoff (5s, 10s, 20s … capped at 2 minutes).
Every retry sends an HTTP `Range` request from the `.part` offset, so a dropped
connection 13 GB into a 14 GB file costs seconds, not the file.

Authentication failures and 404s are not retried — no amount of retrying fixes a
missing token.

Closing the browser doesn't stop anything; closing the manager does, but
re-queueing picks up exactly where it left off. Each file is size-checked before
being moved into place, so a truncated download can't masquerade as a good one.

Tune the attempt count with **Retries per file** in Settings.

### 5. Workflows

Click **Install workflows**. Copies the six bundled graphs into
`<ComfyUI>/user/default/workflows/`, where they appear in ComfyUI's sidebar.

### 6. Launch

Click **Start ComfyUI**, wait for the log to settle, then use the **open
ComfyUI** link in the header. Load a workflow from the sidebar and generate.

---

## What each tab does

| Tab | Purpose |
|---|---|
| **Status** | Environment checklist — Python, git, GPU, checkout, venv, torch, torch-sees-GPU, disk. Refreshes every second. |
| **Setup** | The four provisioning steps, with live streamed output. One at a time. |
| **Models** | Every file in the manifest, grouped, with on-disk state, live download progress and per-file selection. |
| **Civitai** | Add LoRAs, checkpoints and embeddings by URL. The saved list is committed to git. |
| **Workflows** | Copies the bundled graphs into ComfyUI. |
| **Launch** | Start/stop the ComfyUI process, tail its log, open it. |
| **Settings** | Paths, PyTorch channel, bind address, port, parallel downloads, HF token, SHA-256 verification. |

The page polls once a second, so progress, logs and status all update on their
own. The dot next to the title in the header goes red if the manager stops
responding.

---

## The RTX 5090 gotcha

**This is the single most likely thing to bite you.**

Blackwell cards (RTX 50-series) report compute capability **sm_120**. PyTorch
builds before **2.7** — including the very common `2.6.0+cu124` — ship no sm_120
kernels. Torch imports fine, `torch.cuda.is_available()` returns `True`, and then
the first real CUDA operation dies with:

```
CUDA error: no kernel image is available for execution on the device
```

The fix is the **`cu128`** channel (CUDA 12.8) — which is the default in Settings.

The Status tab checks this specifically rather than making you find out the hard
way: it reads the card's actual compute capability and the installed torch
version, and fails the **GPU visible to torch** check with the exact remedy if
they don't match.

To fix an existing bad install, set the channel to `cu128` in Settings and re-run
**Setup → Install PyTorch**. It force-reinstalls, so it will replace the wrong
build.

> **A venv is never portable between machines.** Don't copy `venv/` from another
> box — absolute paths are baked into it. Always run the setup steps on the target.

---

## What gets downloaded

Sizes and SHA-256 digests in `models.manifest.json` were fetched from the
HuggingFace API rather than typed by hand, and the filenames match the workflow
templates that ship with ComfyUI, so the graphs load without touching a dropdown.

| Group | Size | Recommended | What it's for |
|---|---:|:---:|---|
| `flux` | 34.2 GB | ✓ | Flux.1-dev still images |
| `wan21_core` | 21.3 GB | ✓ | WAN 2.1 text-to-video + the shared UMT5 encoder and VAE |
| `wan21_i2v` | 17.7 GB | ✓ | WAN 2.1 image-to-video (+ `clip_vision_h`) |
| `wan21_speed` | 1.4 GB | ✓ | lightx2v step-distill LoRAs for 2.1 |
| `wan22_t2v` | 31.0 GB | ✓ | WAN 2.2 text-to-video, 14B two-expert MoE + 4-step LoRAs |
| `wan22_i2v` | 31.0 GB | ✓ | WAN 2.2 image-to-video, 14B MoE + 4-step LoRAs |
| `wan22_5b` | 11.4 GB | | WAN 2.2 TI2V 5B — faster and lighter, lower fidelity |

**148 GB total; 136.6 GB for the recommended set.** Everything resolves without
authentication — the HF token field exists only for licence-gated repositories.

Things that are easy to get wrong:

- **WAN 2.2 14B is a mixture-of-experts pair.** The high-noise and low-noise
  models both load at once, and each needs its matching LoRA half. You can't use
  just one.
- **WAN 2.2 14B reuses `wan_2.1_vae`.** Only the **5B** model needs `wan2.2_vae`.
- **The lightx2v LoRAs are the biggest single speedup** — roughly 20 steps down to
  4-6. Don't skip them; they're small.
- **`clip_vision_h` is only needed by WAN 2.1 image-to-video.** WAN 2.2 doesn't
  use it, and text-to-video never does.

---

## Civitai LoRAs and checkpoints

The **Civitai** tab adds anything from Civitai — LoRAs, checkpoints, embeddings,
VAEs, ControlNets — on top of the fixed manifest.

Paste a model URL and press **Look up**. It accepts any of these:

```
https://civitai.com/models/264290
https://civitai.com/models/264290?modelVersionId=1558543
https://civitai.com/api/download/models/1558543
264290
```

You get the model name, creator, every version, and the files in each. Pick a
version and a file, confirm the target folder, and **Add to list**.

The target folder is guessed from the Civitai model type — `LORA` → `loras`,
`Checkpoint` → `checkpoints`, `TextualInversion` → `embeddings`, and so on — and
the dropdown lets you override it when the guess is wrong.

### Why the list is committed

`civitai.models.json` **is tracked in git**, unlike `config.json`. Add LoRAs on
your desktop, `git push`, then `git pull` on the 5090 and hit **Download all
missing** — the same set lands there, at the same paths, with the same version
pinned. The file records the model and version id, the exact filename, the target
folder, the size and the SHA-256, so it reproduces exactly rather than
"whatever's newest".

Only your API key stays machine-local.

### API key

Most public models download without one. You need a key for early-access or
login-gated files — create it under **Civitai → Account settings → API Keys** and
paste it into **Settings → Civitai API key**.

Civitai redirects downloads to a signed CDN URL that carries its own
authorization in the query string, so the manager passes your key as a query
parameter rather than a header — an `Authorization` header surviving that
redirect makes the CDN reject the request. If a download fails with HTTP 401 or
403, the key is missing or expired.

### Notes

- Files are matched on disk by name and exact byte size, so a LoRA you already
  have shows as **installed** and won't re-download.
- The file list shows Civitai's own virus-scan result. Models are arbitrary
  pickled or safetensors data from strangers — prefer `.safetensors`, which
  can't execute code on load.
- **Remove** only drops the entry from the list. It never deletes the file from
  disk; do that yourself if you want the space back.

---

## Bundled workflows

Installed into `<ComfyUI>/user/default/workflows/` by the Workflows tab.

| File | Notes |
|---|---|
| `flux_text_to_image.json` | The graph already proven working on the 4090 |
| `sdxl_pony_text_to_image.json` | SDXL / Pony with three LoRA slots — see below |
| `wan2.1_text_to_video_14B.json` | Official template, repointed from the 1.3B default to the 14B model |
| `wan2.1_image_to_video_720p.json` | Official template, repointed from the 480p default to 720p fp8 |
| `wan2.2_text_to_video_14B.json` | Official template, unmodified |
| `wan2.2_image_to_video_14B.json` | Official template, unmodified |
| `wan2.2_ti2v_5B.json` | Official template, unmodified — needs the `wan22_5b` group |

ComfyUI also ships hundreds more templates in its own browser (Workflow →
Browse Templates). Those reference whatever filenames upstream chose, so you may
have to switch a loader dropdown to a model you actually downloaded.

### The SDXL / Pony workflow

`sdxl_pony_text_to_image.json` is laid out left to right in three labelled
groups — **Model + LoRAs**, **Prompt**, **Settings** — with a read-me note on the
canvas. Defaults are Pony-oriented: clip skip `-2`, 832×1216 portrait, 28 steps,
CFG 7.0, `dpmpp_2m` / `karras`.

Nothing in the default manifest fits it, because SDXL and Pony checkpoints live
on Civitai. Add one from the **Civitai** tab, then press **R** in ComfyUI to
refresh the dropdowns.

**The three LoRA slots start bypassed** (drawn dark and translucent). That's
deliberate: a bypassed node passes MODEL and CLIP straight through, so it neither
runs nor validates, and an empty slot can't fail your prompt. To use one, pick a
file and press **Ctrl+B** on the node. Ctrl+B again turns it back off. Chaining
means LoRA 2 stacks on LoRA 1, and so on.

Pony checkpoints also expect the quality-tag prefix — `score_9, score_8_up,
score_7_up` — which is already in the positive prompt. Plain SDXL models don't
want it; delete it and set clip skip to `-1`.

### Turning any workflow into a one-panel control

The WAN 2.2 templates show a single node with every setting promoted onto it.
That's ComfyUI's **subgraph** feature, and you can do it to any workflow yourself:

1. Box-select the nodes you want to hide.
2. Right-click → **Convert to Subgraph**.
3. Open it, right-click a widget → **Promote widget**, for each control you want
   on the outside.

The result collapses to one node exposing just those widgets. Doing it in the
editor is far more reliable than hand-writing the subgraph JSON.

---

## Running it from another machine

Two separate things listen, and they're configured in different places:

| | What sets it | Default |
|---|---|---|
| **The manager** (this app) | `--host` / `--port` on the command line | `127.0.0.1:8500` |
| **ComfyUI** | Bind address / Port in the Settings tab | `127.0.0.1:8188` |

To drive an idle box from your desk, expose both:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -BindHost 0.0.0.0
```

and set **Bind address** to `0.0.0.0` in Settings before starting ComfyUI.

Then open the firewall on the target once:

```powershell
New-NetFirewallRule -DisplayName "ComfyUI Deploy" -Direction Inbound `
  -LocalPort 8500,8188 -Protocol TCP -Action Allow
```

Now browse to `http://<target-ip>:8500` from anywhere on the LAN. Read
[Security](#security) first.

---

## Sharing one model library

Point **Models directory** at a network share or a second drive to avoid
re-downloading 148 GB per machine. The manager only ever reads and writes that
path, and ComfyUI picks models up from wherever it's told.

Already have some of these files? Put them in the right subfolder
(`diffusion_models/`, `text_encoders/`, `vae/`, `loras/`, `clip_vision/`) and the
Models tab will show them as **installed** — matching is by filename and exact
byte size, so nothing gets re-downloaded.

---

## Troubleshooting

**"no kernel image is available for execution on the device"**
Wrong PyTorch for the card. See [the 5090 gotcha](#the-rtx-5090-gotcha).

**Status shows `torch.cuda.is_available()` is False**
Either the NVIDIA driver is missing (the GPU check will also be red), or the
`cpu` channel got installed. Set the right channel and re-run Setup → Install
PyTorch.

**Downloads were interrupted — how do I retry?**
Usually you don't: a file that drops mid-transfer retries itself and resumes from
the `.part` offset. If it exhausted its attempts and shows **failed**, use
**Select all missing → Download** (that selects anything not `installed`,
including `partial` and `wrong size` rows), or tick the single row. Nothing
already downloaded is fetched twice. On the Civitai tab the equivalent is
**Download all missing**.

**A download failed permanently**
The row shows the reason. `HTTP 401/403` means it needs authentication — an HF
token for gated HuggingFace repos (nothing in the default manifest is), or a
Civitai API key for early-access files. `HTTP 404` means the host removed it.
Neither is retried.

**A file says `cancelled` or `failed` but the group says complete**
Fixed — finished jobs whose file verifies on disk are now forgotten, and the
on-disk state wins over a dead job status. If you're on an older build, reload
the page after restarting the manager.

**Downloads are slow**
Raise **Parallel downloads** in Settings (max 6). Past 2-3 you're usually
saturating the link rather than helping.

**A model shows "wrong size"**
The file on disk doesn't match the manifest — a partial copy from elsewhere, or a
different quantisation with the same name. Delete it and re-download.

**Setup step won't start**
Only one runs at a time. Wait for the current one, or check the status pill next
to the log.

**ComfyUI won't start**
Check the Launch log. Almost always a missing venv or an incomplete requirements
install — re-run those Setup steps.

**Manager won't start at all**
Run `python manage.py --doctor`. If the port is taken, use `--port 8600`.

**`ConnectionAbortedError [WinError 10053]` in the console**
Harmless, and fixed in the current build — `git pull` and it stops. Nothing was
ever actually wrong; downloads and setup were unaffected.

The proximate cause is the browser closing a connection while the server is
mid-write: the page polls `/api/state` once a second, so any reload, tab switch
or navigation aborts an in-flight response, and older builds printed a full
traceback for each one.

What made it constant rather than occasional was that `/api/state` used to take
**~1.5 seconds** — the environment probe spawned a subprocess that imported torch
on *every* poll. With a 1-second poll interval, requests overlapped permanently,
so there was always one in flight to abort. The probe is now cached for 20
seconds (and invalidated when config changes or a setup step finishes), which
takes `/api/state` to ~2 ms. Disconnects are also caught rather than printed.

**A custom node fails to install its dependencies**
Check the Python version on the Status tab's *Virtual environment* row. Core
ComfyUI runs on anything 3.10+, but third-party nodes pull compiled packages that
lag new Python releases. If you're on 3.13+ and a node won't build, that's likely
why — see [Which Python](#which-python).

**The header dot is red**
The manager process died or was stopped. Restart it; downloads resume when
re-queued.

---

## Command line

```
python manage.py [--host HOST] [--port PORT] [--no-browser] [--doctor]
```

| Flag | Meaning |
|---|---|
| `--host` | Bind address for the manager. `0.0.0.0` for LAN. Default `127.0.0.1`. |
| `--port` | Manager port. Default `8500`. |
| `--no-browser` | Don't auto-open a browser. |
| `--doctor` | Print the Status checks and exit. Non-zero exit if any fail. |

`--doctor` is the useful one for SSH or a scheduled task:

```
  [ ok ] Manager Python        3.10.11 (Windows 10)
  [ ok ] git available         C:\Program Files\Git\mingw64\bin\git.EXE
  [ ok ] GPU                   NVIDIA GeForce RTX 4090 - 24 GB, driver 596.49
  [ ok ] ComfyUI checkout      H:\LocalAI\ComfyUI
  [ ok ] Virtual environment   H:\LocalAI\ComfyUI\venv\Scripts\python.exe
  [ ok ] PyTorch               2.6.0+cu124 (CUDA 12.4)
  [ ok ] GPU visible to torch  NVIDIA GeForce RTX 4090 - sm_89, 26 GB VRAM
  [ ok ] Disk space            2116 GB free at H:\

  models: 7/21 present - 92.5 GB still to download
```

`bootstrap.ps1` takes `-BindHost`, `-Port` and `-NoBrowser`, and runs its own
preflight (Python version, git, GPU) before handing over to `manage.py`.

---

## HTTP API

Everything the UI does goes through this, so it's all scriptable.

| Method | Path | Body |
|---|---|---|
| `GET` | `/api/state` | — returns config, checks, manifest state, jobs, logs |
| `POST` | `/api/config` | `{"torch_channel":"cu128", ...}` |
| `POST` | `/api/download` | `{"groups":["flux"]}` or `{"files":["ae.safetensors"]}` |
| `POST` | `/api/download/cancel` | `{"all":true}` or `{"key":"loras/thing.safetensors"}` |
| `POST` | `/api/civitai/resolve` | `{"ref":"<url or id>"}` — metadata only, saves nothing |
| `POST` | `/api/civitai/add` | `{"ref":..., "version_id":..., "file_id":..., "folder":"loras"}` |
| `POST` | `/api/civitai/remove` | `{"key":"<versionId>:<fileId>"}` |
| `POST` | `/api/civitai/download` | `{"all":true}` or `{"keys":["..."]}` |
| `POST` | `/api/setup` | `{"step":"clone\|venv\|torch\|requirements"}` |
| `POST` | `/api/workflows/install` | `{}` |
| `POST` | `/api/comfy/start` · `/api/comfy/stop` | `{}` |
| `POST` | `/api/shutdown` | `{}` — stops the manager |

Fetch everything the recommended groups need, headless:

```bash
curl -X POST http://127.0.0.1:8500/api/download \
  -H "Content-Type: application/json" \
  -d '{"groups":["flux","wan21_core","wan21_i2v","wan21_speed","wan22_t2v","wan22_i2v"]}'
```

---

## Repo layout

```
manage.py               entry point (--doctor, --host, --port)
deploy/core.py          config, manifest state, environment probing
deploy/civitai.py       Civitai API client and the saved-model list
deploy/jobs.py          resumable downloader + streamed subprocess tasks
deploy/server.py        stdlib HTTP server and JSON API
deploy/static/          the single-page UI (index.html, app.js, style.css)
models.manifest.json    verified URLs, exact sizes, SHA-256
civitai.models.json     your Civitai picks — committed, syncs across machines
workflows/              graphs installed into ComfyUI
scripts/bootstrap.ps1   preflight + launch for Windows
config.json             local settings — gitignored, never committed
```

`config.json` holds machine-specific paths and your HF token, so it stays out of
git and every machine gets its own. Models are never committed — the repo is
about 370 KB.

**Optional:** tick *Verify SHA-256 after each download* in Settings for full
integrity checking. It's off by default because hashing a 20 GB file takes a
while; the size check already catches truncated transfers, which is the common
failure.

---

## Security

The manager has **no authentication** and by design can run arbitrary setup
commands and write anywhere the user account can reach.

Binding it to `0.0.0.0` exposes that to everyone on the network. Only do it on a
network you trust, and prefer an SSH tunnel over an open port if the network
isn't yours:

```bash
ssh -L 8500:127.0.0.1:8500 user@target-machine
```

Then browse to `http://127.0.0.1:8500` locally with nothing exposed.
