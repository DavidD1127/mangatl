# mangatl

> 漫画 / 条漫的中文嵌字流水线。**OCR 定位 + 人工译文 + 自动排版**，附带一个把"漏翻"抓出来的复检环节。

English summary at the end.

---

## 这个工具解决什么

汉化条漫最耗时的不是翻译，是**把中文塞回原来的气泡里**：找位置、定字号、断行、盖住原文、别把画面糊掉。这些是机械活，但一话就是几百个文本框。

mangatl 把可自动的部分自动化，把必须人判断的地方留出来：

```
图块 ──ingest──▶ 长图 ──ocr──▶ 文本行 ──merge──▶ 气泡块
                                                    │
                                          ┌─────────┴─────────┐
                                          │  人工/模型填译文   │  ← 只有这一步需要人
                                          └─────────┬─────────┘
                                                    ▼
                                               render ──▶ 成品
                                                    │
                                              verify ──▶ 漏翻清单 ──┐
                                                    │              │
                                                    └◀─────────────┘
                                                    ▼
                                                 export
```

中途每一步的产物都是 JSON，可以单独重跑，也可以手改。

## 为什么要 verify

嵌字最容易翻车的不是译文质量，是**漏**：某一句 OCR 没认出来、某个气泡只盖住了一半、某张说明卡整块没翻。

人工核对几百条译文不现实，但"画面里还留着拉丁字母"这件事机器一眼就能看出来。`verify` 会对渲染后的成品再跑一遍 OCR，把纯英文块连同坐标列出来——照着补 `extra` 或 `bbox` 就行。

实测一话 100 多块文本里，这一步能稳定抓出 10～40 处需要补的地方。

## 安装

```bash
pip install -e ".[all]"      # 含 OCR 和 PDF 导出
# 或者按需：
pip install -e .             # 只做渲染/切页，不含 OCR
pip install -e ".[ocr]"      # 加 OCR
```

依赖说明：

| 包 | 用途 | 必需 |
| --- | --- | --- |
| pillow, numpy | 图像处理 | 是 |
| rapidocr-onnxruntime | 文字检测识别 | OCR/复检 |
| pymupdf | 导出 PDF | 可选 |

Windows / macOS / Linux 都能跑，OCR 走 CPU。

## 用法

### 1. 建工作目录

```bash
mangatl init ./my-work --name "某部漫画"
```

会生成 `project.json`，里面有宽度、页高、字体路径等参数。字体没自动找到的话手动填 `font`。

### 2. 收图

把自己的图块按顺序放进目录，然后：

```bash
mangatl ingest ./my-work --chapters 101 --dir ./raw/101 --stitch
```

也可以用 URL 清单（`--urls links.json`，格式是 `["url1","url2"]` 或 `{"101": [...]}`）。下载器只管抓，站点解析写在项目外面。

图块宽于基准宽度（默认 900）会等比缩放到基准宽度——常见于开头的横版扉页。

### 3. 识别

```bash
mangatl ocr ./my-work --chapters 101
```

输出 `ocr_101.json`，一行一条：坐标、原文、置信度。
一话 17 万像素高的长图大约 3～8 分钟（CPU）。

### 4. 聚类 + 出译文模板

```bash
mangatl merge ./my-work --chapters 101 --template
```

输出两份：

- `blocks_101.json` — 气泡块，带 `en` 原文
- `tr_101.json` — **待填的译文表**

### 5. 填译文

`tr_101.json` 的结构：

```jsonc
{
  "skip":  [15, 35],                      // 要丢弃的块（装饰、水印、拟声词）
  "merge": [[10, 11], [38, 39]],          // 同一句被拆成几行，合并；译文写在首 id
  "bbox":  { "19": [560, 39045, 852, 39320] },  // 手动指定覆盖框
  "bg":    { "114": [43, 43, 45] },       // 手动指定填充色（深色卡片用）
  "mask":  [20],                          // 只遮挡不写字（重复的招牌行）
  "extra": [                              // OCR 漏掉、但要补译的
    { "x0": 376, "y0": 40115, "x1": 786, "y1": 40312, "cn": "卡马洪教授" }
  ],
  "text": { "1": "别紧张。", "2": "我已经不是从前的我了。" }
}
```

填完跑渲染。

### 6. 渲染

```bash
mangatl render ./my-work --chapters 101
```

输出 `out/101_01.png …`（默认每 20000px 一段）和 `full_101.png`。

填充用的是**羽化圆角矩形**：取框边一圈像素的中位色当底色，蒙版做高斯模糊，边缘融进原气泡，不会出现方正的白板。

字号策略是"先试整行"——中文比英文短，能一行放下就不折行，避免"亚博/士"这种难看断法。

### 7. 复检

```bash
mangatl verify ./my-work --chapters 101
```

列出还留着的英文块和坐标。照着回第 5 步补。

OCR 或复检过程中，只要有一个图块识别失败，命令就会报错并停止，不会把不完整的结果写成“零残留”。已有的结果文件保持原样；修复依赖或输入后请重新运行，以命令成功完成为准。

### 8. 导出

```bash
mangatl export ./my-work --chapters 101 --format pdf
mangatl export ./my-work --chapters 101 --format cbz
mangatl export ./my-work --format zip        # index.html + 全部分段 PNG
mangatl export ./my-work --chapters 101 --format zip  # 仅打包第 101 话
```

切页不是平均切：每页在目标位置前后 170px 内找一行最接近纯白的，在那儿下刀，避免把对话拦腰截断。

切点超过目标页高时，JPEG 页面会相应加高，保留切点前的全部画面；PDF 仍使用 A4 页面。首尾裁剪按配置像素数处理，不会丢弃整张相交页面。

如果译文缩到最小字号仍放不下，渲染会报出文本块编号，并在替换输出文件前停止。请扩大该块的 `bbox` 或缩短译文后重跑。译文中的手动换行会保留。

**关于画质**：`pdf` / `cbz` 内部存的是 JPEG（质量 92），会有一次编码损失。要完全无损就导出 `zip`——里面的 PNG 是原图直出，配 `index.html` 直接在浏览器里滚动阅读。

## 参数

`project.json`：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `width` | 900 | 拼接基准宽度 |
| `page_height` | 1273 | 导出单页高度（900×1273 ≈ A4 比例） |
| `dpi` | 110 | 导出图片的 DPI 元数据 |
| `font` | 自动探测 | 正文字体，中文必须指定 |
| `skip_top` | 0 | 每章开头丢弃高度（去汉化组扉页） |
| `skip_bottom` | 0 | 每章结尾丢弃高度（去引流尾图） |
| `row_min_score` | 0.40 | OCR 置信度阈值 |

`merge` 的 `max_line_gap` / `max_block_height` 是防"灰块"的两道闸，见 `mangatl/merge.py` 的注释。

## 已知局限

- **翻译不可自动**。工具只负责定位和排版，译文要人给。这也是它没做成"一键出成品"的原因。
- **OCR 只适合定位**。全大写手写体常被识别成大小写混杂（`YEs, Come In.`），内容必须逐条核。
- **排版差异大**。有的作品全是无框浮字，有的气泡规整，`bbox` 策略不可能一套通用，做好手动改几处的准备。
- **拟声词和效果音**默认跳过，不翻。
- **图源不稳定**。站点会换域名、上 Cloudflare，所以下载器故意做得很薄，只吃 URL 清单。

## 用在 agent 里

仓库带一份 `SKILL.md`，写清了给 AI 助手用时的操作顺序、每步该看什么、哪些地方必须停下来让人确认。放进支持 skill 的环境里可以直接调用。

## 开发验证

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试使用合成图片和模拟 OCR，覆盖识别失败、章节选择、切页保真、译文溢出和命令行处理流程，不需要下载漫画或 OCR 模型。中文排版测试需要系统中文字体；GitHub Actions 在 Windows / Linux、Python 3.10 / 3.12 上运行。

## 许可与用途

代码 MIT。**但请只处理你拥有权利的内容**，或所在地区允许的合理使用范围。工具本身不提供、不抓取任何漫画资源。

---

## English

`mangatl` is a semi-automatic lettering pipeline for manga / webtoons: OCR locates text, a human (or model) supplies translations, and the tool renders Chinese back into the original bubbles with feathered fills, automatic line breaking, and font fitting.

Its most useful part is `verify`: after rendering, it OCRs the result again and lists every remaining Latin-script block, which surfaces missed translations and under-covered bubbles that are impractical to find by eye across hundreds of entries.

```bash
pip install -e ".[all]"
mangatl init ./work --name my-comic
mangatl ingest ./work --chapters 101 --dir ./raw/101 --stitch
mangatl ocr ./work --chapters 101
mangatl merge ./work --chapters 101 --template
# edit work/tr_101.json
mangatl render ./work --chapters 101
mangatl verify ./work --chapters 101
mangatl export ./work --chapters 101 --format zip
```

Translation is intentionally left to a human. The tool handles localization, layout, and QA — not the words.

MIT licensed. Only use it on material you have the rights to.
