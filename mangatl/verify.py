"""verify：对渲染后的成品再跑一次 OCR，找出没被盖住的英文。

这是整套流程里最实用的一环。人工核对 200 条译文不现实，但「哪里还留着
拉丁字母」是机器一眼能看出来的——漏译、填充框没盖全、气泡只遮了一半，
都会在这里暴露。

输出的坐标可以直接抄进译文表的 `extra` 或 `bbox`。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from .config import Project

Image.MAX_IMAGE_PIXELS = None

CJK = re.compile(r"[\u4e00-\u9fff]")
LAT = re.compile(r"[A-Za-z]")
WIN, OVERLAP = 1400, 200


def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("缺少 OCR 依赖：pip install rapidocr_onnxruntime") from exc
    return RapidOCR()


def run(project: Project, chapter: int, min_letters: int = 4,
        ignore_margin: bool = True) -> list[dict]:
    full = project.root / f"full_{chapter}.png"
    if not full.exists():
        raise FileNotFoundError(f"{full} 不存在，先跑 render")

    engine = _engine()
    im = Image.open(full).convert("RGB")
    W, H = im.size
    found: dict[tuple, dict] = {}
    tile_path = project.root / "_verify_tile.png"

    y = 0
    while y < H:
        bottom = min(y + WIN, H)
        if bottom - y < 150 and y > 0:
            break
        tile = im.crop((0, y, W, bottom))
        gray = np.asarray(tile.convert("L"))
        if gray.size and float((gray < 225).mean()) < 0.002:
            y += WIN - OVERLAP
            continue
        tile.save(tile_path)
        try:
            res, _ = engine(str(tile_path), use_cls=False)
        except Exception:  # noqa: BLE001
            y += WIN - OVERLAP
            continue
        for item in res or []:
            box, text, score = item[0], item[1], float(item[2])
            if score < 0.5:
                continue
            # 只留纯拉丁块：中英混排说明已经嵌过中文了
            if len(LAT.findall(text)) >= min_letters and not CJK.search(text):
                xs = [p[0] for p in box]
                ys = [p[1] + y for p in box]
                key = (round(min(ys) / 20), text.strip()[:20])
                found[key] = {
                    "x0": round(min(xs), 1), "y0": round(min(ys), 1),
                    "x1": round(max(xs), 1), "y1": round(max(ys), 1),
                    "text": text.strip(), "score": round(score, 3),
                }
        y += WIN - OVERLAP

    tile_path.unlink(missing_ok=True)
    rows = list(found.values())
    if ignore_margin:
        # 扉页/尾页的汉化组署名会一直在，按 project.json 的边距砍掉
        top = project.skip_top
        bottom = H - project.skip_bottom
        rows = [r for r in rows if r["y0"] >= top and r["y1"] <= bottom]
    rows.sort(key=lambda r: r["y0"])
    out = project.root / f"leftover_{chapter}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ch{chapter}: 残留 {len(rows)} 处 -> {out.name}")
    for r in rows:
        print(f"    y={int(r['y0']):>6} x={int(r['x0']):>3}-{int(r['x1']):>3} {r['text'][:64]}")
    return rows
