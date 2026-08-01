"""Build the SDXL / Pony face-detail workflow (ComfyUI UI graph format).

    python tools/gen_face_detail.py workflows/sdxl_face_detail.json

Base generation, then a second pass that re-renders only the face through a
MediaPipe-derived mask — the ComfyUI equivalent of A1111's ADetailer, using
core nodes only.
"""
import json, sys

nodes, links = [], []
_l = [0]


def node(nid, ntype, pos, size, widgets=None, title=None, inputs=None, outputs=None,
         color=None, mode=0):
    n = {"id": nid, "type": ntype, "pos": list(pos), "size": list(size), "flags": {},
         "order": len(nodes), "mode": mode, "inputs": inputs or [], "outputs": outputs or [],
         "properties": {"Node name for S&R": ntype, "cnr_id": "comfy-core"},
         "widgets_values": widgets if widgets is not None else []}
    if title: n["title"] = title
    if color: n.update(color=color[0], bgcolor=color[1])
    nodes.append(n)
    return n


def link(src, ss, dst, ds, t):
    _l[0] += 1
    links.append([_l[0], src["id"], ss, dst["id"], ds, t])
    src["outputs"][ss].setdefault("links", []).append(_l[0])
    dst["inputs"][ds]["link"] = _l[0]


def out(name, t, slot): return {"name": name, "type": t, "links": [], "slot_index": slot}
def inp(name, t):       return {"name": name, "type": t, "link": None}


BLUE, GREEN, PURPLE, RED = ("#223", "#335"), ("#232", "#353"), ("#323", "#535"), ("#533", "#755")

node(1, "MarkdownNote", (20, 20), (470, 430), [
    "## SDXL / Pony with automatic face detail\n\n"
    "Generates an image, finds the face, then re-renders **only the face** at a lower "
    "denoise. This is what ADetailer does in A1111. Both images are saved so you can "
    "compare — `sdxl_base` and `sdxl_face`.\n\n"
    "**Set up**\n\n"
    "1. **Checkpoint** — your SDXL or Pony model\n"
    "2. **LoRA 1-3** — bypassed; select a file and press **Ctrl+B** to enable\n"
    "3. **Prompts** — Pony needs the `score_9, score_8_up…` prefix\n\n"
    "**Tuning the face pass**\n\n"
    "- **denoise** (Face sampler) is the main dial. `0.35` polishes, `0.5` rebuilds, "
    "above `0.6` starts changing who the person is.\n"
    "- **Grow / Feather** widen and soften the mask. Too tight leaves a visible seam "
    "along the jaw; feather is what hides it.\n"
    "- **num_faces** on the detector — raise it for group shots.\n\n"
    "The whole image is VAE round-tripped, so areas outside the mask shift very "
    "slightly. That is normal and not a bug.\n\n"
    "> Dropdown says `undefined`? Press **R** to refresh — ComfyUI rescans folders "
    "on its own, no restart needed."
], title="Read me")

# ------------------------------------------------------------------ base model
ckpt = node(2, "CheckpointLoaderSimple", (20, 480), (400, 100),
            ["PUT_YOUR_SDXL_OR_PONY_MODEL_HERE.safetensors"],
            title="1 - Checkpoint", color=BLUE,
            outputs=[out("MODEL", "MODEL", 0), out("CLIP", "CLIP", 1), out("VAE", "VAE", 2)])
clipskip = node(3, "CLIPSetLastLayer", (20, 630), (400, 60), [-2],
                title="2 - Clip skip (-2 for Pony)", color=BLUE,
                inputs=[inp("clip", "CLIP")], outputs=[out("CLIP", "CLIP", 0)])

loras = []
for i in range(3):
    loras.append(node(10 + i, "LoraLoader", (470, 480 + i * 190), (400, 130),
                      ["PICK_A_LORA.safetensors", 0.8, 0.8],
                      title=f"3 - LoRA {i+1}   -   bypassed, Ctrl+B", color=PURPLE, mode=4,
                      inputs=[inp("model", "MODEL"), inp("clip", "CLIP")],
                      outputs=[out("MODEL", "MODEL", 0), out("CLIP", "CLIP", 1)]))

# ------------------------------------------------------------------ prompts
pos = node(20, "CLIPTextEncode", (920, 480), (450, 200),
           ["score_9, score_8_up, score_7_up, a photograph of a woman in a sunlit "
            "cafe, head and shoulders, natural light, sharp focus"],
           title="4 - Positive", color=GREEN,
           inputs=[inp("clip", "CLIP")], outputs=[out("CONDITIONING", "CONDITIONING", 0)])
neg = node(21, "CLIPTextEncode", (920, 720), (450, 170),
           ["score_6, score_5, score_4, worst quality, low quality, blurry, "
            "deformed face, extra fingers, watermark, text"],
           title="4 - Negative", color=RED,
           inputs=[inp("clip", "CLIP")], outputs=[out("CONDITIONING", "CONDITIONING", 0)])

# ------------------------------------------------------------------ base pass
latent = node(30, "EmptyLatentImage", (1420, 480), (380, 110), [832, 1216, 1],
              title="5 - Size (832x1216 portrait)", color=BLUE,
              outputs=[out("LATENT", "LATENT", 0)])
ks = node(31, "KSampler", (1420, 630), (380, 270),
          [0, "randomize", 28, 7.0, "dpmpp_2m", "karras", 1.0],
          title="6 - Base sampler", color=BLUE,
          inputs=[inp("model", "MODEL"), inp("positive", "CONDITIONING"),
                  inp("negative", "CONDITIONING"), inp("latent_image", "LATENT")],
          outputs=[out("LATENT", "LATENT", 0)])
dec = node(40, "VAEDecode", (1850, 480), (300, 60), title="Decode base",
           inputs=[inp("samples", "LATENT"), inp("vae", "VAE")],
           outputs=[out("IMAGE", "IMAGE", 0)])
node(41, "SaveImage", (1850, 580), (340, 330), ["sdxl_base"],
     title="Save BEFORE (for comparison)",
     inputs=[inp("images", "IMAGE")])

# ------------------------------------------------------------------ face detect
mpload = node(50, "LoadMediaPipeFaceLandmarker", (20, 1000), (400, 80),
              ["mediapipe_face_fp32.safetensors"],
              title="7 - Face detector model", color=GREEN,
              outputs=[out("FACE_DETECTION_MODEL", "FACE_DETECTION_MODEL", 0)])
mpdet = node(51, "MediaPipeFaceLandmarker", (470, 1000), (400, 160),
             ["short", 1, 0.5, "empty"],
             title="8 - Detect faces", color=GREEN,
             inputs=[inp("face_detection_model", "FACE_DETECTION_MODEL"), inp("image", "IMAGE")],
             outputs=[out("face_landmarks", "FACE_LANDMARKS", 0),
                      out("bboxes", "BOUNDING_BOX", 1)])
mpmask = node(52, "MediaPipeFaceMask", (920, 1000), (400, 90), ["all"],
              title="9 - Face mask", color=GREEN,
              inputs=[inp("face_landmarks", "FACE_LANDMARKS")],
              outputs=[out("MASK", "MASK", 0)])
grow = node(53, "GrowMask", (920, 1130), (400, 100), [16, True],
            title="10 - Grow (past the jaw line)", color=GREEN,
            inputs=[inp("mask", "MASK")], outputs=[out("MASK", "MASK", 0)])
feather = node(54, "FeatherMask", (920, 1270), (400, 140), [24, 24, 24, 24],
               title="11 - Feather (hides the seam)", color=GREEN,
               inputs=[inp("mask", "MASK")], outputs=[out("MASK", "MASK", 0)])

# ------------------------------------------------------------------ face pass
facepos = node(60, "CLIPTextEncode", (1420, 1000), (400, 150),
               ["score_9, score_8_up, score_7_up, a detailed face, sharp eyes, "
                "crisp eyelashes, natural skin texture"],
               title="12 - Face prompt", color=GREEN,
               inputs=[inp("clip", "CLIP")], outputs=[out("CONDITIONING", "CONDITIONING", 0)])
enc = node(61, "VAEEncode", (1420, 1190), (400, 70), title="13 - Encode image",
           inputs=[inp("pixels", "IMAGE"), inp("vae", "VAE")],
           outputs=[out("LATENT", "LATENT", 0)])
setmask = node(62, "SetLatentNoiseMask", (1420, 1300), (400, 70),
               title="14 - Restrict noise to the face",
               inputs=[inp("samples", "LATENT"), inp("mask", "MASK")],
               outputs=[out("LATENT", "LATENT", 0)])
ks2 = node(63, "KSampler", (1870, 1000), (380, 270),
           [0, "randomize", 24, 7.0, "dpmpp_2m", "karras", 0.45],
           title="15 - Face sampler  (denoise!)", color=GREEN,
           inputs=[inp("model", "MODEL"), inp("positive", "CONDITIONING"),
                   inp("negative", "CONDITIONING"), inp("latent_image", "LATENT")],
           outputs=[out("LATENT", "LATENT", 0)])
dec2 = node(64, "VAEDecode", (1870, 1310), (300, 60), title="Decode result",
            inputs=[inp("samples", "LATENT"), inp("vae", "VAE")],
            outputs=[out("IMAGE", "IMAGE", 0)])
node(65, "SaveImage", (1870, 1410), (360, 340), ["sdxl_face"],
     title="Save AFTER", inputs=[inp("images", "IMAGE")])

# ------------------------------------------------------------------ wiring
link(ckpt, 1, clipskip, 0, "CLIP")
pm, pc = (ckpt, 0), (clipskip, 0)
for ln in loras:
    link(pm[0], pm[1], ln, 0, "MODEL")
    link(pc[0], pc[1], ln, 1, "CLIP")
    pm, pc = (ln, 0), (ln, 1)

link(pc[0], pc[1], pos, 0, "CLIP")
link(pc[0], pc[1], neg, 0, "CLIP")
link(pc[0], pc[1], facepos, 0, "CLIP")
link(pm[0], pm[1], ks, 0, "MODEL")
link(pos, 0, ks, 1, "CONDITIONING")
link(neg, 0, ks, 2, "CONDITIONING")
link(latent, 0, ks, 3, "LATENT")
link(ks, 0, dec, 0, "LATENT")
link(ckpt, 2, dec, 1, "VAE")
link(dec, 0, nodes[[n["id"] for n in nodes].index(41)], 0, "IMAGE")   # save before

link(mpload, 0, mpdet, 0, "FACE_DETECTION_MODEL")
link(dec, 0, mpdet, 1, "IMAGE")
link(mpdet, 0, mpmask, 0, "FACE_LANDMARKS")
link(mpmask, 0, grow, 0, "MASK")
link(grow, 0, feather, 0, "MASK")

link(dec, 0, enc, 0, "IMAGE")
link(ckpt, 2, enc, 1, "VAE")
link(enc, 0, setmask, 0, "LATENT")
link(feather, 0, setmask, 1, "MASK")
link(pm[0], pm[1], ks2, 0, "MODEL")
link(facepos, 0, ks2, 1, "CONDITIONING")
link(neg, 0, ks2, 2, "CONDITIONING")
link(setmask, 0, ks2, 3, "LATENT")
link(ks2, 0, dec2, 0, "LATENT")
link(ckpt, 2, dec2, 1, "VAE")
link(dec2, 0, nodes[[n["id"] for n in nodes].index(65)], 0, "IMAGE")

graph = {
    "id": "d2e3f4a5-6b7c-4d8e-9f0a-1b2c3d4e5f60", "revision": 0,
    "last_node_id": 65, "last_link_id": _l[0], "nodes": nodes, "links": links,
    "groups": [
        {"id": 1, "title": "Model + LoRAs", "bounding": [10, 450, 870, 620],
         "color": "#3f789e", "font_size": 24, "flags": {}},
        {"id": 2, "title": "Prompt", "bounding": [910, 450, 480, 460],
         "color": "#3f5f3f", "font_size": 24, "flags": {}},
        {"id": 3, "title": "Base generation", "bounding": [1410, 450, 800, 470],
         "color": "#593f9e", "font_size": 24, "flags": {}},
        {"id": 4, "title": "Face detail pass  (the ADetailer bit)",
         "bounding": [10, 960, 2250, 800],
         "color": "#8e5f3f", "font_size": 24, "flags": {}},
    ],
    "config": {}, "extra": {"ds": {"scale": 0.6, "offset": [0, 0]}}, "version": 0.4,
}
json.dump(graph, open(sys.argv[1], "w", encoding="utf-8"), indent=2)
print(f"  wrote {sys.argv[1]}: {len(nodes)} nodes, {len(links)} links")
