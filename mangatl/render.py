"""render：把译文写回画面。

两个细节决定成品观感好坏：

1. 填充用「羽化」而不是硬矩形。取框边一圈像素的中位色当底色，
   用高斯模糊过的圆角矩形蒙版贴上去，边缘就融进原来的气泡/卡片，
   不会露出一块方方正正的白板。
2. 断行优先整行放下。中文比英文短，字号从大往小试，第一个能排成
   单行的字号直接用；实在放不下才折行，且避免末行只剩一个标点。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Project

Image.MAX_IMAGE_PIXELS = None

PUNCT = "，。！？、…「」『』（）—～·：；"
SEG_HEIGHT = 20000   # 成品分段高度，太长浏览器和阅读器都吃力


# ---------------------------------------------------------------- 组装清单

def build_plan(project: Project, chapter: int) -> list[dict]:
    """把 blocks + 译文表合成一份最终渲染清单。"""
    blocks = {b["id"]: b for b in
              json.loads(project.blocks_path(chapter).read_text(encoding="utf-8"))}
    spec = json.loads(project.tr_path(chapter).read_text(encoding="utf-8"))

    skip = set(spec.get("skip", []))
    texts = spec.get("text", {})
    masks = {str(m) for m in spec.get("mask", [])}
    plan: list[dict] = []

    # 1. 合并组：框取并集，译文写在首 id
    for group in spec.get("merge", []):
        head = str(group[0])
        if not texts.get(head):
            continue
        parts = [blocks[i] for i in group if i in blocks]
        if not parts:
            continue
        for i in group[1:]:
            skip.add(i)
        plan.append({
            "id": head,
            "x0": min(p["x0"] for p in parts), "y0": min(p["y0"] for p in parts),
            "x1": max(p["x1"] for p in parts), "y1": max(p["y1"] for p in parts),
            "cn": texts[head], "mode": "mask" if head in masks else "auto",
        })

    # 2. 单块
    done = {p["id"] for p in plan}
    for bid, b in blocks.items():
        key = str(bid)
        if bid in skip or key in done:
            continue
        cn = texts.get(key, "")
        if key in masks:
            plan.append({**b, "id": key, "cn": "", "mode": "mask"})
            continue
        if not cn:
            continue
        plan.append({**b, "id": key, "cn": cn, "mode": "auto"})

    # 3. 凭空补的块（OCR 漏检但画面里有字）
    for e in spec.get("extra", []):
        plan.append({
            "id": e.get("id", f"x{len(plan)}"),
            "x0": e["x0"], "y0": e["y0"], "x1": e["x1"], "y1": e["y1"],
            "cn": e.get("cn", ""), "mode": e.get("mode", "auto"),
        })

    # 4. 手动覆盖
    for p in plan:
        if p["id"] in spec.get("bbox", {}):
            p["x0"], p["y0"], p["x1"], p["y1"] = spec["bbox"][p["id"]]
        if p["id"] in spec.get("bg", {}):
            p["bg"] = spec["bg"][p["id"]]

    plan.sort(key=lambda b: b["y0"])
    return plan


# ---------------------------------------------------------------- 绘制

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _sample_bg(im: Image.Image, box) -> tuple[int, int, int]:
    """取框内侧一圈像素的中位色当底色。"""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    pad = max(2, min(w, h) // 8)
    reg = im.crop((x0 + pad, y0 + pad, x1 - pad, y1 - pad))
    arr = np.asarray(reg.convert("RGB")).reshape(-1, 3)
    if not arr.size:
        return (255, 255, 255)
    return tuple(int(v) for v in np.median(arr, axis=0))


def _feather_fill(im: Image.Image, box, color, radius: int = 4, blur: int = 3) -> None:
    ox, oy = max(0, int(box[0]) - radius - 2), max(0, int(box[1]) - radius - 2)
    ex, ey = min(im.width, int(box[2]) + radius + 2), min(im.height, int(box[3]) + radius + 2)
    if ex - ox < 4 or ey - oy < 4:
        return
    region = im.crop((ox, oy, ex, ey))
    patch = Image.new("RGB", region.size, color)
    mask = Image.new("L", region.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (int(box[0]) - ox, int(box[1]) - oy, int(box[2]) - ox, int(box[3]) - oy),
        radius=radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    im.paste(Image.composite(patch, region, mask), (ox, oy))


def _wrap(text: str, font, max_w: float) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _fit(text: str, font_path: str, box_w: float, box_h: float,
         min_size: int = 11, max_size: int = 44):
    """挑一个既能放下、又尽量保持单行的字号。"""
    # 先试整行
    for size in range(max_size, 27, -1):
        f = _load_font(font_path, size)
        if f.getlength(text) <= box_w and int(size * 1.32) <= box_h:
            return f, [text], int(size * 1.32)

    fallback = None
    for size in range(max_size, min_size - 1, -1):
        f = _load_font(font_path, size)
        lines = _wrap(text, f, box_w)
        lh = int(size * 1.32)
        if lh * len(lines) <= box_h and all(f.getlength(l) <= box_w for l in lines):
            if fallback is None:
                fallback = (f, lines, lh)
            tail = [c for c in lines[-1] if c not in PUNCT]
            if len(lines) == 1 or len(tail) >= 2:
                return f, lines, lh
    if fallback:
        return fallback
    f = _load_font(font_path, min_size)
    return f, _wrap(text, f, box_w), int(min_size * 1.2)


def draw_block(im: Image.Image, draw: ImageDraw.ImageDraw, blk: dict,
               font_path: str, pad: int = 8) -> None:
    box = (blk["x0"] - pad, blk["y0"] - pad, blk["x1"] + pad, blk["y1"] + pad)
    mode = blk.get("mode", "auto")

    if mode == "mask":
        _feather_fill(im, box, tuple(blk.get("bg") or _sample_bg(im, box)))
        return

    if mode == "outline":
        fg, stroke = (255, 255, 255), (0, 0, 0)
    else:
        bg = tuple(blk.get("bg") or _sample_bg(im, box))
        lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        fg = (17, 17, 17) if lum > 120 else (248, 248, 248)
        stroke = (255, 255, 255) if lum <= 120 else None
        _feather_fill(im, box, bg)

    text = blk.get("cn", "")
    if not text:
        return
    bw, bh = box[2] - box[0] - 10, box[3] - box[1] - 8
    font, lines, lh = _fit(text, font_path, bw, bh)
    ty = box[1] + (box[3] - box[1] - lh * len(lines)) // 2
    for line in lines:
        tw = font.getlength(line)
        draw.text((box[0] + (box[2] - box[0] - tw) / 2, ty), line, font=font, fill=fg,
                  stroke_width=2 if stroke else 0, stroke_fill=stroke)
        ty += lh


# ---------------------------------------------------------------- 主流程

def run(project: Project, chapter: int, seg_height: int = SEG_HEIGHT) -> list[Path]:
    strip_path = project.strip_path(chapter)
    if not strip_path.exists():
        raise FileNotFoundError(f"{strip_path} 不存在，先跑 ingest")

    plan = build_plan(project, chapter)
    im = Image.open(strip_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    for blk in sorted(plan, key=lambda b: b["y0"]):
        draw_block(im, draw, blk, project.font)

    out_dir = project.out_dir()
    for old in out_dir.glob(f"{chapter}_*.png"):
        old.unlink()

    files = []
    n = 0
    for top in range(0, im.height, seg_height):
        n += 1
        p = out_dir / f"{chapter}_{n:02d}.png"
        im.crop((0, top, im.width, min(top + seg_height, im.height))).save(
            p, optimize=True)
        files.append(p)
    full = project.root / f"full_{chapter}.png"
    im.save(full, optimize=True)
    print(f"  ch{chapter}: {len(plan)} 块 -> {len(files)} 段（{full.name}）")
    return files
