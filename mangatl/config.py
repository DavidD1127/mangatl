"""项目配置与路径约定。

一个工作目录（project root）里所有中间产物都按 `<步骤>_<章节>.json` 落盘，
这样任何一步都可以单独重跑，也方便人工编辑。
"""
from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field, asdict
from pathlib import Path


def default_font() -> str:
    """挑一个系统里存在的中文字体。"""
    system = platform.system()
    candidates = {
        "Windows": [
            r"C:\Windows\Fonts\msyhbd.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\msyh.ttc",
        ],
        "Darwin": [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ],
        "Linux": [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ],
    }.get(system, [])
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


@dataclass
class Project:
    root: Path
    """工作目录，所有产物都写在这下面。"""

    name: str = "untitled"

    width: int = 900
    """拼接基准宽度。图块宽于它会被等比缩放到这个宽度。"""

    page_height: int = 1273
    """导出 PDF/CBZ 时的单页高度（900x1273 ≈ A4 纵横比）。"""

    dpi: int = 110
    """导出图片的 DPI 元数据。"""

    font: str = field(default_factory=default_font)
    """正文字体路径。留空则用 Pillow 默认字体（中文会缺字）。"""

    skip_top: int = 0
    """每章开头要丢弃的高度，用于去掉汉化组扉页。"""

    skip_bottom: int = 0
    """每章结尾要丢弃的高度，用于去掉引流尾图。"""

    row_min_score: float = 0.40
    """OCR 置信度低于它的行直接丢弃。"""

    # ---------- 路径 ----------

    def p(self, name: str) -> Path:
        return self.root / name

    def pages_dir(self, chapter: int) -> Path:
        return self.root / "pages" / str(chapter)

    def strip_path(self, chapter: int) -> Path:
        return self.root / f"strip_{chapter}.png"

    def ocr_path(self, chapter: int) -> Path:
        return self.root / f"ocr_{chapter}.json"

    def blocks_path(self, chapter: int) -> Path:
        return self.root / f"blocks_{chapter}.json"

    def tr_path(self, chapter: int) -> Path:
        """译文表：{id: 中文} 加上可选的 skip / merge / bbox / bg / extra。"""
        return self.root / f"tr_{chapter}.json"

    def out_dir(self) -> Path:
        d = self.root / "out"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def segments(self, chapter: int) -> list[Path]:
        return sorted(self.root.glob(f"out/{chapter}_*.png"))

    # ---------- 序列化 ----------

    def save(self) -> Path:
        path = self.root / "project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["root"] = str(self.root)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, root: str | Path) -> "Project":
        root = Path(root).resolve()
        path = root / "project.json"
        if not path.exists():
            raise FileNotFoundError(f"{path} 不存在，先跑 `mangatl init {root}`")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["root"] = root
        return cls(**data)

    def chapters(self) -> list[int]:
        """从 pages/ 下的子目录推断章节号。"""
        base = self.root / "pages"
        if not base.exists():
            return []
        out = []
        for d in base.iterdir():
            if d.is_dir() and d.name.isdigit():
                out.append(int(d.name))
        return sorted(out)
