"""ocr：把长图切窗跑 OCR，输出带全局坐标的文本行。

两个关键点，都是踩坑换来的：

1. `use_cls=False`。方向分类器对竖长条几乎无用，关掉之后单窗耗时
   从几十秒降到一两秒。
2. 空白窗直接跳过。webtoon 里纯白间隔很多，先算一次灰度非白占比，
   低于阈值就不进模型。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .config import Project

Image.MAX_IMAGE_PIXELS = None

WIN = 1400       # 单窗高度
OVERLAP = 200    # 窗间重叠，避免切断同一行字
BLANK_MAX = 0.002  # 非白像素占比低于它就认为整窗空白


def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "缺少 OCR 依赖：pip install rapidocr_onnxruntime"
        ) from exc
    return RapidOCR()


def run(project: Project, chapter: int, win: int = WIN, overlap: int = OVERLAP) -> Path:
    if not 0 <= overlap < win:
        raise ValueError("OCR 参数必须满足 0 <= overlap < win")
    strip_path = project.strip_path(chapter)
    if not strip_path.exists():
        raise FileNotFoundError(f"{strip_path} 不存在，先跑 ingest")

    engine = _engine()
    im = Image.open(strip_path)
    W, H = im.size
    print(f"  ch{chapter}: {W}x{H}")

    seen: dict[tuple, dict] = {}
    y = 0
    tile_path = project.root / "_tile.png"
    while y < H:
        bottom = min(y + win, H)
        if bottom - y < 150 and y > 0:
            break
        tile = im.crop((0, y, W, bottom))

        gray = np.asarray(tile.convert("L"))
        if gray.size and float((gray < 225).mean()) < BLANK_MAX:
            y += win - overlap
            continue

        tile.save(tile_path)
        try:
            res, _ = engine(str(tile_path), use_cls=False)
        except Exception as exc:
            tile_path.unlink(missing_ok=True)
            im.close()
            raise RuntimeError(f"ch{chapter}: 识别在 y={y} 失败，未生成本次 OCR 结果") from exc

        for item in res or []:
            box, text, score = item[0], item[1], float(item[2])
            if score < project.row_min_score or len(text.strip()) < 2:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] + y for p in box]
            # 同一行在不同窗里可能被识别两次，用位置+文本前缀做键去重
            key = (round(min(xs) / 10), round(min(ys) / 10), text.strip()[:14])
            cand = {
                "x0": round(min(xs), 1), "x1": round(max(xs), 1),
                "y0": round(min(ys), 1), "y1": round(max(ys), 1),
                "text": text.strip(), "score": round(score, 3),
            }
            prev = seen.get(key)
            if prev is None or cand["score"] > prev["score"]:
                seen[key] = cand
        y += win - overlap

    tile_path.unlink(missing_ok=True)
    im.close()
    rows = sorted(seen.values(), key=lambda r: (r["y0"], r["x0"]))
    out = project.ocr_path(chapter)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ch{chapter}: {len(rows)} 行 -> {out.name}")
    return out
