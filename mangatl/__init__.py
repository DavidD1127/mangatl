"""mangatl —— 漫画翻译嵌字流水线。

分四层，每层的产物都落盘，可以单独重跑：

    ingest   图块 -> 拼接长图
    ocr      长图 -> 文本行（坐标 + 原文）
    merge    文本行 -> 气泡块（带间隔守卫）
    render   气泡块 + 译文 -> 嵌字成品
    verify   成品再 OCR -> 找出没被覆盖的英文
    export   成品 -> png / pdf / cbz / html / zip
"""

__version__ = "0.1.0"

from .config import Project  # noqa: F401
