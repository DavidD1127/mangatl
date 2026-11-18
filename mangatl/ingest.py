"""ingest：把零散的图块收进项目，拼成一条竖长图。

图源随作品和站点变化很大，所以这里只做两件事：
1. 把图按序放进 `pages/<chapter>/`（文件名自然排序 = 阅读顺序）
2. 按配置宽度拼接成 `strip_<chapter>.png`

下载器不内置站点解析。拿直链的逻辑（绕 Cloudflare、解析章节页 JSON 之类）
写在项目外面，把 URL 清单交给 `--urls` 就行。
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from PIL import Image

from .config import Project

Image.MAX_IMAGE_PIXELS = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def collect_from_dir(project: Project, chapter: int, src: str | Path) -> int:
    """把目录里的图片按名字顺序拷进 pages/<chapter>/。"""
    src = Path(src)
    files = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"})
    dst = project.pages_dir(chapter)
    dst.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files, 1):
        target = dst / f"{i:02d}{f.suffix.lower()}"
        if not target.exists():
            shutil.copy2(f, target)
    return len(files)


def collect_from_urls(project: Project, chapter: int, urls: list[str],
                      referer: str = "", timeout: int = 90) -> int:
    """按顺序下载 URL 清单。

    很多图床会看 Referer，所以要能传；失败的单张会被跳过并打印，
    不会中断整章。
    """
    dst = project.pages_dir(chapter)
    dst.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer

    done = 0
    for i, url in enumerate(urls, 1):
        ext = ".webp" if ".webp" in url.lower() else ".jpg"
        target = dst / f"{i:02d}{ext}"
        if target.exists() and target.stat().st_size > 1000:
            done += 1
            continue
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if len(data) < 1000:
                raise ValueError("响应太小，可能被拦截")
            target.write_bytes(data)
            done += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 第 {i} 张失败：{exc}")
    return done


def stitch(project: Project, chapter: int) -> Path:
    """把一话的图块拼成一条长图。

    宽于基准宽度的图块会等比缩放到基准宽度（常见于开头的横版扉页），
    矮于宽度的部分两边留白——直接贴左会比留白更难看。
    """
    src = project.pages_dir(chapter)
    files = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"})
    if not files:
        raise FileNotFoundError(f"{src} 里没有图片")

    parts: list[Image.Image] = []
    for f in files:
        im = Image.open(f).convert("RGB")
        if im.width != project.width:
            h = round(im.height * project.width / im.width)
            im = im.resize((project.width, h), Image.LANCZOS)
        parts.append(im)

    total = sum(im.height for im in parts)
    strip = Image.new("RGB", (project.width, total), "white")
    y = 0
    for im in parts:
        strip.paste(im, (0, y))
        y += im.height

    out = project.strip_path(chapter)
    strip.save(out, optimize=True)
    print(f"  ch{chapter}: {len(parts)} 块 -> {strip.width}x{strip.height}")
    return out
