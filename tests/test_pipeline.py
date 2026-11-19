"""针对漏检、导出和排版的数据完整性回归测试。"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

from mangatl import export, ocr, render, verify
from mangatl.cli import main
from mangatl.config import Project


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Project(root=Path(self.tmp.name), width=40, page_height=80)

    def test_verify_failure_does_not_report_success(self):
        Image.new("RGB", (40, 300), "black").save(self.project.root / "full_1.png")
        with patch.object(verify, "_engine") as factory:
            factory.return_value.side_effect = RuntimeError("engine failed")
            with self.assertRaisesRegex(RuntimeError, "复检.*失败"):
                verify.run(self.project, 1)
        self.assertFalse((self.project.root / "leftover_1.json").exists())
        self.assertFalse((self.project.root / "_verify_tile.png").exists())

    def test_ocr_failure_does_not_write_partial_result(self):
        Image.new("RGB", (40, 300), "black").save(self.project.strip_path(1))
        with patch.object(ocr, "_engine") as factory:
            factory.return_value.side_effect = RuntimeError("engine failed")
            with self.assertRaisesRegex(RuntimeError, "识别.*失败"):
                ocr.run(self.project, 1)
        self.assertFalse(self.project.ocr_path(1).exists())
        self.assertFalse((self.project.root / "_tile.png").exists())

    def test_zip_respects_chapter_selection(self):
        self.project.save()
        for ch in (1, 2):
            self.project.pages_dir(ch).mkdir(parents=True)
            Image.new("RGB", (40, 100), "white").save(
                self.project.out_dir() / f"{ch}_01.png")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["export", str(self.project.root), "--chapters", "2", "--format", "zip"])
        with zipfile.ZipFile(self.project.root / "dist/untitled_cn.zip") as archive:
            self.assertEqual(set(archive.namelist()), {"index.html", "out/2_01.png"})
            html = archive.read("index.html").decode("utf-8")
            self.assertIn("第 2 话", html)
            self.assertNotIn("第 1 话", html)

    def test_missing_selected_chapter_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            export.to_zip(self.project, self.project.root / "book.zip", chapters=[1])
        self.assertFalse((self.project.root / "book.zip").exists())

    def test_paginate_preserves_rows_after_blank_cut(self):
        # 空白切点晚于目标高度，旧逻辑会丢掉 80..89 行。
        image = Image.new("RGB", (40, 180), "black")
        for y in range(80, 90):
            for x in range(40):
                image.putpixel((x, y), (255, 0, 0))
        image.save(self.project.out_dir() / "1_01.png")
        with patch.object(export, "cut_points", return_value=[90]):
            pages = export.paginate(self.project, 1, self.project.root / "page-test")
        red_rows = 0
        for page in pages:
            with Image.open(page) as result:
                pixels = np.asarray(result)
                red_rows += int(((pixels[:, :, 0].mean(axis=1) > 180)
                                 & (pixels[:, :, 1].mean(axis=1) < 60)).sum())
        self.assertEqual(red_rows, 10)

    def test_bottom_margin_only_removes_configured_rows(self):
        self.project.skip_bottom = 10
        image = Image.new("RGB", (40, 100), "black")
        image.save(self.project.out_dir() / "1_01.png")
        with patch.object(export, "cut_points", return_value=[]):
            pages = export.paginate(self.project, 1, self.project.root / "page-test")
        self.assertEqual(len(pages), 1)
        with Image.open(pages[0]) as result:
            self.assertEqual(result.height, 90)
            self.assertLess(np.asarray(result).mean(), 2)

    def test_text_overflow_fails_before_output_is_replaced(self):
        font = self.project.font
        if not font:
            self.skipTest("系统没有可用中文字体")
        Image.new("RGB", (40, 100), "white").save(self.project.strip_path(1))
        self.project.blocks_path(1).write_text(json.dumps([
            {"id": 1, "x0": 5, "y0": 5, "x1": 15, "y1": 15}
        ]), encoding="utf-8")
        self.project.tr_path(1).write_text(json.dumps({
            "text": {"1": "这是一段不可能放进这么小的气泡里的很长很长的译文" * 10}
        }), encoding="utf-8")
        output = self.project.out_dir() / "1_01.png"
        output.write_bytes(b"existing output")
        with self.assertRaisesRegex(ValueError, "放不下"):
            render.run(self.project, 1)
        self.assertEqual(output.read_bytes(), b"existing output")

    def test_verify_reports_remaining_english(self):
        Image.new("RGB", (40, 300), "black").save(self.project.root / "full_1.png")
        result = [[[[1, 10], [35, 10], [35, 25], [1, 25]], "HELLO", 0.99]]
        with patch.object(verify, "_engine") as factory:
            factory.return_value.return_value = (result, None)
            rows = verify.run(self.project, 1)
        self.assertEqual(rows[0]["text"], "HELLO")
        self.assertEqual(json.loads((self.project.root / "leftover_1.json").read_text()), rows)

    def test_invalid_window_and_page_size_are_rejected(self):
        with self.assertRaises(ValueError):
            ocr.run(self.project, 1, win=200, overlap=200)
        with self.assertRaises(ValueError):
            export.cut_points(Image.new("RGB", (10, 100)), page_height=0)

    def test_explicit_line_break_is_preserved(self):
        if not self.project.font:
            self.skipTest("系统没有可用中文字体")
        _, lines, _ = render._fit("你好\n再见", self.project.font, 300, 200)
        self.assertEqual(lines, ["你好", "再见"])

    def test_cli_pipeline_with_synthetic_image(self):
        work = self.project.root / "work"
        raw = self.project.root / "raw"
        raw.mkdir()
        Image.new("RGB", (240, 300), "black").save(raw / "01.png")
        result = [[[[30, 40], [210, 40], [210, 140], [30, 140]], "HELLO", 0.99]]
        with contextlib.redirect_stdout(io.StringIO()):
            main(["init", str(work), "--width", "240", "--page-height", "160"])
            project = Project.load(work)
            if not project.font:
                self.skipTest("系统没有可用中文字体")
            main(["ingest", str(work), "--chapters", "1", "--dir", str(raw), "--stitch"])
            with patch.object(ocr, "_engine") as factory:
                factory.return_value.return_value = (result, None)
                main(["ocr", str(work), "--chapters", "1"])
            main(["merge", str(work), "--chapters", "1", "--template"])
            project.tr_path(1).write_text(json.dumps({"text": {"1": "你好"}}), encoding="utf-8")
            main(["render", str(work), "--chapters", "1"])
            main(["export", str(work), "--chapters", "1", "--format", "cbz"])
            main(["export", str(work), "--chapters", "1", "--format", "zip"])
        with Image.open(work / "full_1.png") as output:
            self.assertEqual(output.size, (240, 300))
        with zipfile.ZipFile(work / "dist/work_1.cbz") as archive:
            self.assertTrue(archive.namelist())
        with zipfile.ZipFile(work / "dist/work_cn.zip") as archive:
            self.assertIn("out/1_01.png", archive.namelist())


if __name__ == "__main__":
    unittest.main()
