# 招标公告与附件Block转换流程

> 状态（2026-09-17）：Parser 代码为 `2.1.0`（含PDF原生水印过滤）。存在两个Block目录——正式`dataset_build/blocks/`仍为Parser `2.0.0`全量产物（274,597 Blocks）；v0.2展示与上传流水线使用`run/parser_2_1_20260828/notices`（Parser 2.1.0隔离全量，274,586 Blocks）。本文流程描述对两个版本均适用，数字以2.0.0全量产物为准。技术字段定义见`docs/BLOCK_PARSER.md`和`docs/block_schema.json`。

## 1. Block是什么

Block不是最终实体识别结果，也不是单独的纯文本文件。它是从原始HTML或附件中提取出的、带来源坐标的最小内容单元，并以JSON保存。

一个公告JSON会同时保存：

- 公告元数据；
- 原HTML及附件中每个文件的状态、哈希和容器路径；
- 按原顺序排列的段落、标题、表格、OCR文字、元数据和错误Block；
- 解析器版本、配置摘要和统计信息。

模型真正读取的是Block里的`text`或`rows`。之所以使用JSON，是为了让后续筛选、实体抽取、证据回指和金标重建都能知道文字来自哪个文件、哪一页、哪个Sheet或哪一行。

## 2. 当前端到端流程

```text
mirror_task1/notices/<notice_id>.html
+ mirror_task1/attachments/<notice_id>.zip
  → 按文件头识别真实类型
  → ZIP/RAR安全递归解包
  → 按HTML、Office、PDF、图片等格式提取
  → PDF页级强水印识别、表格抽取前字符过滤、表格与段落去重、扫描页OCR
  → 统一为带来源坐标的Blocks
  → 生成稳定内容寻址block_id
  → 写入逐公告JSON和全量解析报告
  → 本地Block筛选
  → LangGraph实体抽取
```

从原始文件到Block完全由本地代码完成，不调用大模型API。大模型只在后续实体抽取阶段使用。

## 3. 输入与输出

输入：

```text
dataset_build/mirror_task1/notices/<notice_id>.html
dataset_build/mirror_task1/attachments/<notice_id>.zip
dataset_build/manifests/manifest.json
```

输出：

```text
dataset_build/blocks/notices/<notice_id>.json
dataset_build/blocks/parse_report.json
```

关键版本字段：

```json
{
  "schema_version": "1.1",
  "parser_version": "2.0.0",
  "parser_config_digest": "61bfe1df950c6cd2a13ad44d5844382f9349151bfaa03f27fdab07147c17bcbc"
}
```

比较不同批次、复用旧金标或断点前，必须先比较`parser_version + parser_config_digest`。

Parser 2.1.0的PDF水印过滤默认开启；`--no-pdf-watermark-filter`只用于隔离的新旧对照实验，不应写回正式目录。

## 4. 不同格式的提取方式

| 类型 | 当前处理流程 | 进入同一公告Block |
|---|---|---|
| HTML | lxml清除脚本、样式和导航噪声，按页面顺序提取标题、段落和展开合并单元格后的表格 | 是 |
| DOCX | python-docx按文档顺序读取段落和表格；内嵌图片单独OCR | 是 |
| DOC | LibreOffice无界面转DOCX，再走DOCX流程；失败则生成明确`error`，不读取OLE乱码 | 是 |
| XLSX | openpyxl遍历全部Sheet、展开合并单元格；超长表每500行分块并重复表头 | 是 |
| XLS | 优先LibreOffice转XLSX，失败时用xlrd兜底 | 是 |
| PDF | 最新代码先在页级确认完整旋转/半透明/灰色水印，仅在表格字符完整复原同一序列时于抽取前过滤；随后提取文本和表格、抑制重叠段落，原生正文不足50字符的页进入OCR | 是 |
| JPG/PNG/TIFF | RapidOCR/ONNX提取文字并记录平均置信度 | 是 |
| ZIP | 全部成员先做安全校验和落盘，再递归解析；限制深度、文件数、展开体积和压缩比 | 是 |
| 分卷RAR | `.part1/.part2/...`先归组，只从首卷整体解压，后续卷不再逐个解析 | 是 |
| TXT/JSON | 分别生成段落Block和元数据Block | 是 |
| DWG/SXZB4等 | 不伪造文本，文档状态记为`unsupported` | 只记录状态 |

一个公告的HTML、全部附件及递归附件都会整合在同一个`blocks`数组中；每个Block仍保留独立`source.container_path`，因此不会丢失文件边界。

## 5. 稳定Block ID

旧版顺序号`notice_id:b000001`已经停用，因为解析顺序或OCR参数变化会导致后续金标ID整体漂移。

当前格式为：

```text
<notice_id>:blk_<24位SHA-256前缀>
```

哈希包含公告ID、Block类型、稳定来源坐标、正文和二维表格内容。内容和稳定来源不变时ID保持稳定；内容真实变化时ID变化。完全重复且发生冲突时使用确定性后缀。

金标和模型结果仍应同时保存Block ID、表格行号、容器路径和解析版本，不能只依赖哈希ID。

## 6. 环境

统一使用Conda环境`Aproject`：

```powershell
conda run -n Aproject python -m pip install -r requirements-parsing.txt
```

已安装并验证：

- Python 3.11；
- PyMuPDF、python-docx、openpyxl、xlrd、lxml、Pillow；
- RapidOCR + ONNX Runtime，不需要PyTorch；
- 项目内LibreOffice 26.2.5：`third_party/LibreOffice/program/soffice.exe`。

LibreOffice转换使用独立用户配置目录，避免多worker互相锁定。

## 7. 标准转换命令

全量重建：

```powershell
$env:PYTHONIOENCODING='utf-8'
conda run -n Aproject python scripts/parse_blocks.py `
  --workers 4 `
  --ocr rapidocr `
  --max-ocr-pages-per-pdf 20 `
  --skip-ocr-if-scan-pages-over 0 `
  --pdf-table-text-overlap-threshold 0.5 `
  --legacy-office-backend libreoffice `
  --overwrite
```

指定公告重跑：

```powershell
conda run -n Aproject python scripts/parse_blocks.py `
  --ids <notice_id> `
  --workers 1 `
  --ocr rapidocr `
  --max-ocr-pages-per-pdf 20 `
  --skip-ocr-if-scan-pages-over 0 `
  --pdf-table-text-overlap-threshold 0.5 `
  --legacy-office-backend libreoffice `
  --overwrite
```

少量关键PDF需要完整OCR时，把`--max-ocr-pages-per-pdf`改成`0`。不建议直接对全部长PDF无限制OCR。

## 8. 当前291篇全量结果

`dataset_build/blocks/parse_report.json`记录：

```text
公告：291/291落盘，公告级失败0
文档：1,503
Blocks：274,597

文档状态：
  ok           1,471
  partial         23
  error            2
  unsupported      7

Block类型：
  paragraph   261,181
  table         7,048
  heading       4,860
  ocr_text      1,263
  metadata        243
  error             2
```

全量目录已统一为Parser 2.0.0和同一配置摘要，不再是新旧混合目录。

## 9. 已修复的问题

1. Block ID从全局顺序号改为稳定内容寻址ID，并新增解析版本和配置摘要；
2. 分卷RAR从逐卷错误解析改为完整归组后由首卷解压；
3. PDF原生段落与结构化表格的重叠内容按bbox抑制；
4. 启用LibreOffice处理老版DOC/XLS，启用RapidOCR处理图片和扫描页；
5. DOCX中单张WDP等不支持图片失败会隔离，不再让整个文档失败。

## 10. 当前解析缺口

两个文档级error仍未关闭：

- `20260814_27139211`的一份PDF被PyMuPDF报告为关闭或加密；
- `20260815_27141274`的一份疑似老版DOC文件LibreOffice转换失败。

七个`unsupported`主要是DWG、SXZB4和GEF等专业格式。另有23个`partial`，主要来自PDF只OCR前20个扫描页、空Sheet、单张内嵌图片OCR为空等。公告HTML和其他附件仍可能可用，因此这些状态不等于整篇公告失败。

风险最大的召回缺口是长扫描PDF第20页之后的内容。选择金标或发现结果附件位于后页时，应对该公告定向全页OCR并重新运行下游筛选与证据校验。

## 11. 重跑后的连锁操作

重新解析任何公告后，不应只替换Block JSON。推荐依次执行：

```text
重跑指定公告Parser
  → 重跑该公告Selector
  → 若属于金标，重建金标索引并validate_gold
  → 删除或强制刷新该公告旧Agent断点
  → 重新抽取、合并和入库
```

当前Selector断点和Agent断点都含版本或内容摘要，但仍应检查输出manifest，避免把不同解析配置的产物混合统计。

## 12. 校验

```powershell
conda run -n Aproject python -m pytest tests/unit/test_parsing.py -q
conda run -n Aproject python scripts/validate_gold.py
```

解析成功只代表结构可用，不代表所有文字都正确。正式评测前还需人工抽检复杂PDF表格、OCR低置信文字、LibreOffice转换表格以及文档级error/partial样本。
