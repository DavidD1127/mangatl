"""merge：把 OCR 的行聚成气泡级的块。

这里有一条硬性守卫，是踩过坑才加的：

同一个气泡里的多行，行间距不会太大。如果两行的间距超过行高的一定倍数，
它们很可能分属画面不同位置的两处文字（webtoon 里对白常散落在整张画面中）。
强行合并会把中间那一大片画面框进去，填色时直接糊成一块灰板。

`max_line_gap` 和 `max_block_height` 就是这个守卫的两道闸。
"""
from __future__ import annotations

import json
import re

from .config import Project

# 汉化组署名、站点水印、页码之类，不该进译文
DECOR = re.compile(
    r"(asura|discord|mangadex|batoto|webtoon\s*ip\s*holder|read\s*at|"
    r"for\s*the\s*fastest|translator|proofreader|^\d{1,3}$)",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text.lower())


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def load_rows(project: Project, chapter: int, skip_top: int = 0) -> list[dict]:
    rows = json.loads(project.ocr_path(chapter).read_text(encoding="utf-8"))
    out = []
    for r in rows:
        if r["y1"] < skip_top:
            continue
        if DECOR.search(r["text"]):
            continue
        r["h"] = r["y1"] - r["y0"]
        out.append(r)
    # 同一位置的近似文本只留置信度高的那条
    seen: dict[tuple, dict] = {}
    for r in out:
        key = (round(r["y0"] / 26), _norm(r["text"]))
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r
    return list(seen.values())


def build_blocks(
    rows: list[dict],
    max_line_gap: float = 0.95,
    max_block_height: float = 3.5,
    h_overlap: float = 0.45,
) -> list[dict]:
    """贪心聚类。

    max_line_gap      纵向间距 / 行高 的上限
    max_block_height  合并后总高 / 平均行高 的上限
    h_overlap         水平重叠占较窄行的比例下限
    """
    rows = sorted(rows, key=lambda r: (r["y0"], r["x0"]))
    groups: list[list[dict]] = []

    for r in rows:
        placed = False
        for g in groups:
            last = g[-1]
            same_line = abs(r["y0"] - last["y0"]) < max(12, last["h"] * 0.6)
            near_x = (_overlap(r["x0"], r["x1"], last["x0"], last["x1"]) > 0
                      or (r["x0"] - last["x1"]) < last["h"] * 3)
            if same_line and near_x:
                g.append(r)
                placed = True
                break

            gap = r["y0"] - last["y1"]
            heights = [x["h"] for x in g]
            avg_h = sum(heights) / len(heights)
            span = r["y1"] - g[0]["y0"]

            gap_ok = -avg_h * 0.4 < gap < avg_h * max_line_gap
            height_ok = span < avg_h * max_block_height
            width = min(r["x1"] - r["x0"], g[0]["x1"] - g[0]["x0"])
            width_ok = _overlap(r["x0"], r["x1"], g[0]["x0"], g[0]["x1"]) > h_overlap * max(1.0, width)

            if gap_ok and height_ok and width_ok:
                g.append(r)
                placed = True
                break
        if not placed:
            groups.append([r])

    blocks = []
    for g in groups:
        blocks.append({
            "x0": round(min(x["x0"] for x in g), 1),
            "y0": round(min(x["y0"] for x in g), 1),
            "x1": round(max(x["x1"] for x in g), 1),
            "y1": round(max(x["y1"] for x in g), 1),
            "lines": len(g),
            "en": " ".join(x["text"] for x in g),
        })
    blocks.sort(key=lambda b: b["y0"])
    for i, b in enumerate(blocks, 1):
        b["id"] = i
    return blocks


def run(project: Project, chapter: int, skip_top: int | None = None) -> list[dict]:
    top = project.skip_top if skip_top is None else skip_top
    rows = load_rows(project, chapter, skip_top=top)
    blocks = build_blocks(rows)
    out = project.blocks_path(chapter)
    out.write_text(json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ch{chapter}: {len(rows)} 行 -> {len(blocks)} 块 -> {out.name}")
    return blocks


def export_template(project: Project, chapter: int) -> None:
    """生成一份空的译文表，供人工/模型填写。

    结构：
        skip   要丢弃的块 id
        merge  要合并的 id 组，译文写在首 id 上
        bbox   {id: [x0,y0,x1,y1]} 手动改框
        bg     {id: [r,g,b]} 手动指定填充色
        mask   [id] 只遮挡不写字
        extra  [{x0,y0,x1,y1,cn}] 凭空补的块
        text   {id: 中文}
    """
    if project.blocks_path(chapter).exists():
        blocks = json.loads(project.blocks_path(chapter).read_text(encoding="utf-8"))
    else:
        blocks = []
    template = {
        "skip": [],
        "merge": [],
        "bbox": {},
        "bg": {},
        "mask": [],
        "extra": [],
        "text": {str(b["id"]): "" for b in blocks},
    }
    out = project.tr_path(chapter)
    if out.exists():
        print(f"  tr_{chapter}.json 已存在，不覆盖")
        return
    out.write_text(json.dumps(template, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ch{chapter}: 译文模板 -> {out.name}（{len(blocks)} 条待填）")
