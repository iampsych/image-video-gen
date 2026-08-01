"""Build an SDXL / Pony text-to-image workflow in ComfyUI's UI graph format.

Widget orders and link types come from the node schemas introspected out of the
installed ComfyUI, not from memory.
"""
import json, sys

nodes, links = [], []
_link = [0]


def node(nid, ntype, pos, size, widgets=None, title=None, inputs=None, outputs=None,
         color=None, mode=0):
    n = {
        "id": nid, "type": ntype, "pos": list(pos), "size": list(size),
        "flags": {}, "order": len(nodes), "mode": mode,
        "inputs": inputs or [], "outputs": outputs or [],
        "properties": {"Node name for S&R": ntype, "cnr_id": "comfy-core"},
        "widgets_values": widgets if widgets is not None else [],
    }
    if title: n["title"] = title
    if color: n.update(color=color[0], bgcolor=color[1])
    nodes.append(n)
    return n


def link(src, src_slot, dst, dst_slot, ltype):
    _link[0] += 1
    lid = _link[0]
    links.append([lid, src["id"], src_slot, dst["id"], dst_slot, ltype])
    out = src["outputs"][src_slot]
    out.setdefault("links", [])
    out["links"].append(lid)
    dst["inputs"][dst_slot]["link"] = lid
    return lid


def out(name, t, slot):   return {"name": name, "type": t, "links": [], "slot_index": slot}
def inp(name, t):         return {"name": name, "type": t, "link": None}


BLUE   = ("#223", "#335")
GREEN  = ("#232", "#353")
PURPLE = ("#323", "#535")

# ---------------------------------------------------------------- column 1
note = node(1, "MarkdownNote", (20, 20), (430, 320), [
    "## SDXL / Pony — text to image\n\n"
    "**Set these, left to right:**\n\n"
    "1. **Checkpoint** — your SDXL or Pony model (`models/checkpoints`)\n"
    "2. **Clip skip** — `-2` for Pony, `-1` for most plain SDXL\n"
    "3. **LoRA 1-3** — all three start **bypassed** (dark purple). Select a file, "
    "then **Ctrl+B** on the node to switch it on. Ctrl+B again to turn it off.\n"
    "4. **Prompts** — Pony needs the `score_9, score_8_up…` prefix\n"
    "5. **Size** — 832×1216 portrait, 1216×832 landscape, 1024×1024 square\n"
    "6. **Sampler** — 25-30 steps, CFG 6-8\n\n"
    "No Pony model yet? Add one from the **Civitai** tab in the deploy manager, "
    "then press **R** here to refresh the dropdowns."
], title="Read me")

ckpt = node(2, "CheckpointLoaderSimple", (20, 380), (400, 100),
            ["PUT_YOUR_SDXL_OR_PONY_MODEL_HERE.safetensors"],
            title="1 · Checkpoint", color=BLUE,
            outputs=[out("MODEL", "MODEL", 0), out("CLIP", "CLIP", 1), out("VAE", "VAE", 2)])

clipskip = node(3, "CLIPSetLastLayer", (20, 530), (400, 60), [-2],
                title="2 · Clip skip  (-2 for Pony)", color=BLUE,
                inputs=[inp("clip", "CLIP")],
                outputs=[out("CLIP", "CLIP", 0)])

# ---------------------------------------------------------------- column 2
lora_nodes = []
for i in range(3):
    # mode 4 = BYPASS: MODEL and CLIP pass straight through, the node never runs
    # and never validates. Ctrl+B on the node turns a slot on.
    ln = node(10 + i, "LoraLoader", (470, 380 + i * 190), (400, 130),
              ["PICK_A_LORA.safetensors", 0.8, 0.8],
              title=f"3 · LoRA {i + 1}   —   bypassed, Ctrl+B to enable",
              color=PURPLE, mode=4,
              inputs=[inp("model", "MODEL"), inp("clip", "CLIP")],
              outputs=[out("MODEL", "MODEL", 0), out("CLIP", "CLIP", 1)])
    lora_nodes.append(ln)

# ---------------------------------------------------------------- column 3
pos = node(20, "CLIPTextEncode", (920, 380), (450, 220),
           ["score_9, score_8_up, score_7_up, "
            "a photograph of a red fox in autumn woodland, golden hour light, "
            "shallow depth of field, highly detailed"],
           title="4 · Positive prompt", color=GREEN,
           inputs=[inp("clip", "CLIP")],
           outputs=[out("CONDITIONING", "CONDITIONING", 0)])

neg = node(21, "CLIPTextEncode", (920, 640), (450, 200),
           ["score_6, score_5, score_4, worst quality, low quality, jpeg artifacts, "
            "blurry, watermark, signature, text"],
           title="4 · Negative prompt", color=("#533", "#755"),
           inputs=[inp("clip", "CLIP")],
           outputs=[out("CONDITIONING", "CONDITIONING", 0)])

# ---------------------------------------------------------------- column 4
latent = node(30, "EmptyLatentImage", (1420, 380), (380, 110), [832, 1216, 1],
              title="5 · Size  (832×1216 portrait)", color=BLUE,
              outputs=[out("LATENT", "LATENT", 0)])

ks = node(31, "KSampler", (1420, 540), (380, 280),
          [0, "randomize", 28, 7.0, "dpmpp_2m", "karras", 1.0],
          title="6 · Sampler", color=BLUE,
          inputs=[inp("model", "MODEL"), inp("positive", "CONDITIONING"),
                  inp("negative", "CONDITIONING"), inp("latent_image", "LATENT")],
          outputs=[out("LATENT", "LATENT", 0)])

# ---------------------------------------------------------------- column 5
dec = node(40, "VAEDecode", (1850, 380), (300, 60),
           title="Decode",
           inputs=[inp("samples", "LATENT"), inp("vae", "VAE")],
           outputs=[out("IMAGE", "IMAGE", 0)])

save = node(41, "SaveImage", (1850, 490), (400, 460), ["SDXL"],
            title="Save", inputs=[inp("images", "IMAGE")])

# ---------------------------------------------------------------- wiring
link(ckpt, 1, clipskip, 0, "CLIP")                       # CLIP -> clip skip
prev_model, prev_clip = (ckpt, 0), (clipskip, 0)
for ln in lora_nodes:
    link(prev_model[0], prev_model[1], ln, 0, "MODEL")
    link(prev_clip[0], prev_clip[1], ln, 1, "CLIP")
    prev_model, prev_clip = (ln, 0), (ln, 1)

link(prev_clip[0], prev_clip[1], pos, 0, "CLIP")
link(prev_clip[0], prev_clip[1], neg, 0, "CLIP")
link(prev_model[0], prev_model[1], ks, 0, "MODEL")
link(pos, 0, ks, 1, "CONDITIONING")
link(neg, 0, ks, 2, "CONDITIONING")
link(latent, 0, ks, 3, "LATENT")
link(ks, 0, dec, 0, "LATENT")
link(ckpt, 2, dec, 1, "VAE")
link(dec, 0, save, 0, "IMAGE")

graph = {
    "id": "b1f0c2a4-5d6e-4f70-9a8b-2c3d4e5f6a7b",
    "revision": 0,
    "last_node_id": 41,
    "last_link_id": _link[0],
    "nodes": nodes,
    "links": links,
    "groups": [
        {"id": 1, "title": "Model + LoRAs", "bounding": [10, 350, 870, 610],
         "color": "#3f789e", "font_size": 24, "flags": {}},
        {"id": 2, "title": "Prompt", "bounding": [910, 350, 480, 500],
         "color": "#3f5f3f", "font_size": 24, "flags": {}},
        {"id": 3, "title": "Settings", "bounding": [1410, 350, 400, 480],
         "color": "#593f9e", "font_size": 24, "flags": {}},
    ],
    "config": {},
    "extra": {"ds": {"scale": 0.7, "offset": [0, 0]}},
    "version": 0.4,
}

path = sys.argv[1]
with open(path, "w", encoding="utf-8") as f:
    json.dump(graph, f, indent=2)
print(f"  wrote {path}: {len(nodes)} nodes, {len(links)} links")
