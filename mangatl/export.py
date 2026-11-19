"""export：把成品长图切成页，导出成各种格式。

切页不是平均切。每页在目标位置前后一段范围内找一行最接近纯白的，
在那里下刀——否则一条对话会被拦腰截断。
"""
from __future__ import annotations

from html import escape
import shutil
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from .config import Project

Image.MAX_IMAGE_PIXELS = None

SEARCH = 170  # 找空白行的搜索半径


def cut_points(strip: Image.Image, page_height: int, search: int = SEARCH) -> list[int]:
    """返回切点列表（不含首尾）。"""
    if page_height <= 0 or search < 0:
        raise ValueError("page_height 必须大于 0，search 不能小于 0")
    arr = np.asarray(strip.convert("L"))
    h = strip.height
    cuts, y = [], 0
    while True:
        target = y + page_height
        if target >= h:
            break
        lo = max(y + 1, y + page_height // 2, target - search)
        hi = min(h - 2, target + search)
        best, best_v = target, -1e9
        for yy in range(lo, hi, 2):
            # 越白越好，同时轻微偏好靠近目标位置
            score = float(arr[yy].mean()) - abs(yy - target) * 0.02
            if score > best_v:
                best_v, best = score, yy
        cuts.append(best)
        y = best
    return cuts


def paginate(project: Project, chapter: int, tmp_dir: Path) -> list[Path]:
    """按空白切点分页；切点晚于目标时扩展页面，保留全部画面。"""
    files = project.segments(chapter)
    if not files:
        raise FileNotFoundError(f"{project.out_dir()} 里没有 {chapter} 的分段图")

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    pages: list[Path] = []
    last = files[-1]
    idx = 0

    for i, f in enumerate(files):
        with Image.open(f) as source:
            strip = source.convert("RGB")
        top = min(project.skip_top, strip.height) if i == 0 else 0
        bottom = max(top, strip.height - project.skip_bottom) if f == last else strip.height
        if top >= bottom:
            strip.close()
            continue
        if top or bottom != strip.height:
            cropped = strip.crop((0, top, strip.width, bottom))
            strip.close()
            strip = cropped
        bounds = [0] + cut_points(strip, project.page_height) + [strip.height]
        for a, b in zip(bounds, bounds[1:]):
            piece = strip.crop((0, a, strip.width, b))
            page = Image.new("RGB", (project.width, max(project.page_height, b - a)), (255, 255, 255))
            page.paste(piece, (0, 0))
            idx += 1
            out = tmp_dir / f"{idx:04d}.jpg"
            page.save(out, quality=92, optimize=True,
                      dpi=(project.dpi, project.dpi))
            pages.append(out)
            piece.close()
            page.close()
        strip.close()
    return pages


def to_pdf(pages: list[Path], out: Path) -> Path:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("导出 PDF 需要 pymupdf：pip install pymupdf") from exc
    doc = pymupdf.open()
    W, H = 595.0, 842.0  # A4
    for img in pages:
        page = doc.new_page(width=W, height=H)
        page.insert_image(pymupdf.Rect(0, 0, W, H), filename=str(img))
    doc.save(str(out), deflate=True, garbage=3)
    doc.close()
    return out


def to_cbz(pages: list[Path], out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for p in pages:
            z.write(p, arcname=p.name)
    return out


HTML_TPL = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; background:#111013; color:#e7e3ea;
         font-family:"Microsoft YaHei",system-ui,sans-serif; }}
  main {{ max-width:900px; margin:0 auto; }}
  h2 {{ font-size:17px; padding:26px 16px 8px; color:#cdbfe8; margin:0; }}
  img {{ display:block; width:100%; height:auto; background:#fff; }}
</style>
</head>
<body><main>
{body}
</main></body></html>
"""


def to_html(project: Project, title: str = "漫画中文嵌字版",
            chapters: list[int] | None = None) -> Path:
    """生成本地阅读页，引用同目录的分段 PNG。"""
    chapters = project.chapters() if chapters is None else sorted(set(chapters))
    body = []
    for ch in chapters:
        files = project.segments(ch)
        if not files:
            continue
        body.append(f'<h2>第 {ch} 话</h2>')
        for f in files:
            body.append(f'<img src="out/{f.name}" loading="lazy" alt="{ch}">')
    out = project.root / "index.html"
    out.write_text(HTML_TPL.format(title=escape(title), body="\n".join(body)), encoding="utf-8")
    return out


def to_zip(project: Project, out: Path, chapters: list[int] | None = None) -> Path:
    """把 index.html 和所选章节的分段 PNG 打成一个包。

    PNG 是无损的，所以这里是唯一不产生二次压缩的导出路径。
    """
    chapters = project.chapters() if chapters is None else sorted(set(chapters))
    files = []
    for ch in chapters:
        segments = project.segments(ch)
        if not segments:
            raise FileNotFoundError(f"缺少第 {ch} 话的分段图，请先 render")
        files.extend(segments)
    if not files:
        raise FileNotFoundError("没有可导出的分段图，请先 render")
    html = to_html(project, chapters=chapters)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        z.write(html, "index.html")
        for f in files:
            z.write(f, f"out/{Path(f).name}")
    return out


def run(project: Project, chapter: int, fmt: str, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (project.root / "dist")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = project.root / f"_pages_{chapter}"

    pages = paginate(project, chapter, tmp)
    stem = f"{project.name}_{chapter}"
    try:
        if fmt == "pdf":
            out = to_pdf(pages, out_dir / f"{stem}.pdf")
        elif fmt == "cbz":
            out = to_cbz(pages, out_dir / f"{stem}.cbz")
        elif fmt == "jpg":
            target = out_dir / f"{stem}_pages"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(tmp, target)
            out = target
        else:
            raise ValueError(f"不认识的格式：{fmt}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    size = out.stat().st_size / 1024 / 1024 if out.is_file() else 0
    print(f"  ch{chapter}: {len(pages)} 页 -> {out.name}"
          + (f"  {size:.1f} MB" if size else ""))
    return out
