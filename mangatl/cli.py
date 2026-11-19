"""命令行入口。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, ingest, merge, ocr, render, verify, export
from .config import Project


def _chapters(project: Project, raw: str | None) -> list[int]:
    if raw and raw != "all":
        return [int(x) for x in raw.replace(" ", "").split(",") if x]
    found = project.chapters()
    if not found:
        raise SystemExit("pages/ 下没有章节，先 ingest")
    return found


# ---------------------------------------------------------------- 子命令

def cmd_init(args) -> None:
    root = Path(args.dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = Project(root=root, name=args.name or root.name,
                      width=args.width, page_height=args.page_height)
    path = project.save()
    print(f"已创建 {path}")
    if not project.font:
        print("! 没找到中文字体，请手动在 project.json 里填 font")


def cmd_ingest(args) -> None:
    project = Project.load(args.dir)
    chapters = _chapters(project, args.chapters)
    for ch in chapters:
        if args.dir_source:
            n = ingest.collect_from_dir(project, ch, args.dir_source.replace("{ch}", str(ch)))
            print(f"  ch{ch}: 收入 {n} 张")
        elif args.urls:
            urls = json.loads(Path(args.urls).read_text(encoding="utf-8"))
            if isinstance(urls, dict):
                urls = urls[str(ch)]
            n = ingest.collect_from_urls(project, ch, urls, referer=args.referer or "")
            print(f"  ch{ch}: 下载 {n} 张")
        if args.stitch:
            ingest.stitch(project, ch)


def cmd_ocr(args) -> None:
    project = Project.load(args.dir)
    for ch in _chapters(project, args.chapters):
        ocr.run(project, ch)


def cmd_merge(args) -> None:
    project = Project.load(args.dir)
    for ch in _chapters(project, args.chapters):
        merge.run(project, ch)
        if args.template:
            merge.export_template(project, ch)


def cmd_render(args) -> None:
    project = Project.load(args.dir)
    for ch in _chapters(project, args.chapters):
        render.run(project, ch)


def cmd_verify(args) -> None:
    project = Project.load(args.dir)
    for ch in _chapters(project, args.chapters):
        verify.run(project, ch)


def cmd_export(args) -> None:
    project = Project.load(args.dir)
    out_dir = Path(args.out).resolve() if args.out else None
    chapters = _chapters(project, args.chapters)
    for ch in chapters:
        if args.format == "zip":
            continue
        export.run(project, ch, args.format, out_dir)
    if args.format == "zip":
        target = (out_dir or (project.root / "dist"))
        target.mkdir(parents=True, exist_ok=True)
        out = export.to_zip(project, target / f"{project.name}_cn.zip", chapters=chapters)
        print(f"  -> {out.name}  {out.stat().st_size/1024/1024:.0f} MB")


# ---------------------------------------------------------------- 解析

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mangatl",
        description="漫画翻译嵌字流水线：OCR 定位 -> 人工填译 -> 自动嵌字 -> 复检 -> 导出",
    )
    p.add_argument("--version", action="version", version=f"mangatl {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("init", help="建立工作目录")
    d.add_argument("dir")
    d.add_argument("--name")
    d.add_argument("--width", type=int, default=900)
    d.add_argument("--page-height", type=int, default=1273)
    d.set_defaults(func=cmd_init)

    d = sub.add_parser("ingest", help="收图并拼接长图")
    d.add_argument("dir")
    d.add_argument("--chapters", help="101 或 101,102；省略=全部")
    d.add_argument("--dir", dest="dir_source", help="图块目录，可用 {ch} 占位")
    d.add_argument("--urls", help="URL 清单 json（list 或 {ch: list}）")
    d.add_argument("--referer", help="下载时的 Referer")
    d.add_argument("--stitch", action="store_true", help="收完立即拼接")
    d.set_defaults(func=cmd_ingest)

    d = sub.add_parser("ocr", help="识别文本行")
    d.add_argument("dir")
    d.add_argument("--chapters")
    d.set_defaults(func=cmd_ocr)

    d = sub.add_parser("merge", help="行 -> 气泡块")
    d.add_argument("dir")
    d.add_argument("--chapters")
    d.add_argument("--template", action="store_true", help="顺便生成空的译文表")
    d.set_defaults(func=cmd_merge)

    d = sub.add_parser("render", help="按译文渲染成品")
    d.add_argument("dir")
    d.add_argument("--chapters")
    d.set_defaults(func=cmd_render)

    d = sub.add_parser("verify", help="复检残留英文")
    d.add_argument("dir")
    d.add_argument("--chapters")
    d.set_defaults(func=cmd_verify)

    d = sub.add_parser("export", help="导出成品")
    d.add_argument("dir")
    d.add_argument("--chapters")
    d.add_argument("--format", default="pdf",
                   choices=["pdf", "cbz", "jpg", "zip"],
                   help="zip 会打包 index.html + 全部分段 PNG（无损）")
    d.add_argument("--out")
    d.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
