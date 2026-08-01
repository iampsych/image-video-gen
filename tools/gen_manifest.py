"""Generate models.manifest.json with exact sizes + sha256 pulled from the HF API."""
import json, urllib.request, sys

CACHE = {}


def siblings(repo):
    if repo not in CACHE:
        url = f"https://huggingface.co/api/models/{repo}?blobs=true"
        CACHE[repo] = json.load(urllib.request.urlopen(url)).get("siblings", [])
    return CACHE[repo]


def meta(repo, path):
    for s in siblings(repo):
        if s["rfilename"] == path:
            lfs = s.get("lfs") or {}
            return s.get("size"), (lfs.get("sha256") or lfs.get("oid"))
    raise SystemExit(f"NOT FOUND: {repo}/{path}")


WAN21 = "Comfy-Org/Wan_2.1_ComfyUI_repackaged"
WAN22 = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"
KIJAI = "Kijai/WanVideo_comfy"
FLUXTE = "comfyanonymous/flux_text_encoders"

GROUPS = [
    {
        "id": "flux",
        "name": "Flux.1-dev — image generation",
        "summary": "High-quality still images. This is the setup already proven working on the 4090.",
        "recommended": True,
        "models": [
            ("Comfy-Org/flux1-dev", "flux1-dev.safetensors", "diffusion_models", "Main Flux transformer (fp16). Load with weight_dtype fp8_e4m3fn to halve VRAM."),
            (FLUXTE, "t5xxl_fp16.safetensors", "text_encoders", "T5 text encoder, full precision."),
            (FLUXTE, "clip_l.safetensors", "text_encoders", "CLIP-L text encoder."),
            ("ffxvs/vae-flux", "ae.safetensors", "vae", "Flux VAE. Ungated mirror — the Black Forest Labs copy requires a licence-gated HF token."),
        ],
    },
    {
        "id": "wan21_core",
        "name": "WAN 2.1 — text-to-video (base)",
        "summary": "14B text-to-video plus the shared UMT5 encoder and VAE. Required by every other WAN group.",
        "recommended": True,
        "models": [
            (WAN21, "split_files/diffusion_models/wan2.1_t2v_14B_fp8_scaled.safetensors", "diffusion_models", "WAN 2.1 text-to-video 14B."),
            (WAN21, "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoders", "UMT5-XXL encoder — shared by WAN 2.1 and 2.2."),
            (WAN21, "split_files/vae/wan_2.1_vae.safetensors", "vae", "WAN VAE — also used by the WAN 2.2 14B models."),
        ],
    },
    {
        "id": "wan21_i2v",
        "name": "WAN 2.1 — image-to-video",
        "summary": "Animate a still (e.g. a Flux render). Needs clip_vision_h, which plain text-to-video does not use.",
        "recommended": True,
        "models": [
            (WAN21, "split_files/diffusion_models/wan2.1_i2v_720p_14B_fp8_scaled.safetensors", "diffusion_models", "720p image-to-video 14B. The bundled template defaults to the 480p variant — switch the loader dropdown."),
            (WAN21, "split_files/clip_vision/clip_vision_h.safetensors", "clip_vision", "Vision encoder required by WAN 2.1 image-to-video."),
        ],
    },
    {
        "id": "wan21_speed",
        "name": "WAN 2.1 — lightx2v speed LoRAs",
        "summary": "Step-distilled LoRAs: ~20 steps down to 4-6. The single biggest speedup for WAN 2.1.",
        "recommended": True,
        "models": [
            (KIJAI, "Lightx2v/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank64_bf16.safetensors", "loras", "Speed LoRA for WAN 2.1 text-to-video."),
            (KIJAI, "Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "loras", "Speed LoRA for WAN 2.1 image-to-video."),
        ],
    },
    {
        "id": "wan22_t2v",
        "name": "WAN 2.2 — text-to-video (14B MoE)",
        "summary": "Two-expert architecture: high-noise and low-noise models load together. Reuses the WAN 2.1 VAE and UMT5 encoder.",
        "recommended": True,
        "models": [
            (WAN22, "split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "diffusion_models", "High-noise expert (early denoising steps)."),
            (WAN22, "split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "diffusion_models", "Low-noise expert (late denoising steps)."),
            (WAN22, "split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors", "loras", "4-step speed LoRA, high-noise half."),
            (WAN22, "split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors", "loras", "4-step speed LoRA, low-noise half."),
        ],
    },
    {
        "id": "wan22_i2v",
        "name": "WAN 2.2 — image-to-video (14B MoE)",
        "summary": "Best-quality image-to-video. Does not need clip_vision.",
        "recommended": True,
        "models": [
            (WAN22, "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "diffusion_models", "High-noise expert."),
            (WAN22, "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "diffusion_models", "Low-noise expert."),
            (WAN22, "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "loras", "4-step speed LoRA, high-noise half."),
            (WAN22, "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "loras", "4-step speed LoRA, low-noise half."),
        ],
    },
    {
        "id": "wan22_5b",
        "name": "WAN 2.2 — TI2V 5B (fast, optional)",
        "summary": "Single 5B model doing both text- and image-to-video. Much faster and lighter than the 14B pair; lower fidelity. Needs its own VAE.",
        "recommended": False,
        "models": [
            (WAN22, "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", "diffusion_models", "Combined text/image-to-video 5B."),
            (WAN22, "split_files/vae/wan2.2_vae.safetensors", "vae", "WAN 2.2 VAE — required by the 5B model only."),
        ],
    },
]

out = {
    "schema": 1,
    "note": "Sizes and sha256 digests fetched from the HuggingFace API. Filenames match the workflow templates bundled with ComfyUI.",
    "groups": [],
}

for g in GROUPS:
    models = []
    for repo, path, folder, note in g["models"]:
        size, sha = meta(repo, path)
        fname = path.rsplit("/", 1)[-1]
        models.append({
            "file": fname,
            "folder": folder,
            "url": f"https://huggingface.co/{repo}/resolve/main/{path}",
            "repo": repo,
            "size": size,
            "sha256": sha,
            "note": note,
        })
        print(f"  {size/1e9:7.2f} GB  {folder}/{fname}", file=sys.stderr)
    out["groups"].append({
        "id": g["id"], "name": g["name"], "summary": g["summary"],
        "recommended": g["recommended"],
        "bytes": sum(m["size"] or 0 for m in models),
        "models": models,
    })

total = sum(gr["bytes"] for gr in out["groups"])
print(f"\nTOTAL {total/1e9:.1f} GB across {sum(len(gr['models']) for gr in out['groups'])} files", file=sys.stderr)

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print("written:", sys.argv[1], file=sys.stderr)
