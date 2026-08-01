"""Build the video upscale / frame-interpolation workflow (ComfyUI UI graph format)."""
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


BLUE, GREEN, PURPLE = ("#223", "#335"), ("#232", "#353"), ("#323", "#535")

node(1, "MarkdownNote", (20, 20), (470, 340), [
    "## Upscale a video you generated\n\n"
    "**Two independent things you can do:**\n\n"
    "- **Spatial** — `Upscale Image (using Model)` makes each frame bigger and sharper.\n"
    "- **Temporal** — `Frame Interpolate` invents in-between frames for smoother motion.\n\n"
    "**Steps**\n\n"
    "1. Drop your video into `ComfyUI/input/`, then pick it in **Load Video**.\n"
    "2. Choose an upscale model. A **2x** model is usually better for video than 4x — "
    "less over-sharpening and far less VRAM.\n"
    "3. **Frame Interpolate is bypassed** by default. Select a RIFE model and press "
    "**Ctrl+B** on both purple nodes to switch it on.\n"
    "4. **Set `fps` on Create Video.** WAN clips are **16 fps**. If you interpolate at "
    "multiplier 2, set it to **32** to keep real time — leave it at 16 and you get "
    "half-speed slow motion, which is sometimes what you want.\n\n"
    "Audio is carried through automatically if the source had any."
], title="Read me")

load = node(2, "LoadVideo", (20, 400), (400, 120), [""],
            title="1 · Load video  (from ComfyUI/input)", color=BLUE,
            outputs=[out("VIDEO", "VIDEO", 0)])

comp = node(3, "GetVideoComponents", (20, 570), (400, 110),
            title="2 · Split into frames + audio", color=BLUE,
            inputs=[inp("video", "VIDEO")],
            outputs=[out("images", "IMAGE", 0), out("audio", "AUDIO", 1),
                     out("fps", "FLOAT", 2), out("bit_depth", "INT", 3)])

upmodel = node(4, "UpscaleModelLoader", (480, 400), (400, 80), ["RealESRGAN_x2.pth"],
               title="3 · Upscale model", color=GREEN,
               outputs=[out("UPSCALE_MODEL", "UPSCALE_MODEL", 0)])

upscale = node(5, "ImageUpscaleWithModel", (480, 530), (400, 90),
               title="4 · Upscale every frame", color=GREEN,
               inputs=[inp("upscale_model", "UPSCALE_MODEL"), inp("image", "IMAGE")],
               outputs=[out("IMAGE", "IMAGE", 0)])

interpmodel = node(6, "FrameInterpolationModelLoader", (940, 400), (400, 80),
                   ["rife_v4.26.safetensors"],
                   title="5 · RIFE model  —  bypassed, Ctrl+B", color=PURPLE, mode=4,
                   outputs=[out("INTERP_MODEL", "INTERP_MODEL", 0)])

interp = node(7, "FrameInterpolate", (940, 530), (400, 120), [2],
              title="6 · Interpolate  —  bypassed, Ctrl+B", color=PURPLE, mode=4,
              inputs=[inp("interp_model", "INTERP_MODEL"), inp("images", "IMAGE")],
              outputs=[out("IMAGE", "IMAGE", 0)])

create = node(8, "CreateVideo", (1400, 400), (380, 130), [16.0, 8],
              title="7 · Rebuild video  (set fps!)", color=BLUE,
              inputs=[inp("images", "IMAGE"), inp("audio", "AUDIO")],
              outputs=[out("VIDEO", "VIDEO", 0)])

save = node(9, "SaveVideo", (1400, 580), (380, 140), ["video/upscaled", "auto", "auto"],
            title="8 · Save", color=BLUE,
            inputs=[inp("video", "VIDEO")])

link(load, 0, comp, 0, "VIDEO")
link(comp, 0, upscale, 1, "IMAGE")
link(upmodel, 0, upscale, 0, "UPSCALE_MODEL")
link(upscale, 0, interp, 1, "IMAGE")
link(interpmodel, 0, interp, 0, "INTERP_MODEL")
link(interp, 0, create, 0, "IMAGE")
link(comp, 1, create, 1, "AUDIO")
link(create, 0, save, 0, "VIDEO")

graph = {
    "id": "c7d8e9f0-1a2b-4c3d-8e5f-6a7b8c9d0e1f", "revision": 0,
    "last_node_id": 9, "last_link_id": _l[0],
    "nodes": nodes, "links": links,
    "groups": [
        {"id": 1, "title": "Source", "bounding": [10, 370, 420, 320],
         "color": "#3f789e", "font_size": 24, "flags": {}},
        {"id": 2, "title": "Spatial upscale", "bounding": [470, 370, 420, 260],
         "color": "#3f5f3f", "font_size": 24, "flags": {}},
        {"id": 3, "title": "Temporal (optional)", "bounding": [930, 370, 420, 290],
         "color": "#593f9e", "font_size": 24, "flags": {}},
        {"id": 4, "title": "Output", "bounding": [1390, 370, 400, 360],
         "color": "#3f789e", "font_size": 24, "flags": {}},
    ],
    "config": {}, "extra": {"ds": {"scale": 0.75, "offset": [0, 0]}}, "version": 0.4,
}
json.dump(graph, open(sys.argv[1], "w", encoding="utf-8"), indent=2)
print(f"  wrote {sys.argv[1]}: {len(nodes)} nodes, {len(links)} links")
