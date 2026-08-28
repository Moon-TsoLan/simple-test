# 公告与附件统一 Block 解析器

## 目标与边界

解析器把“一篇 HTML 公告 + 同 ID 附件 ZIP”转换为一个 JSON。所有内容都进入统一 `blocks` 数组，表格同时保留二维 `rows` 和适合直接送入模型的 Markdown `text`；每个 block 均携带文件、页码、Sheet、段落或表格序号等来源坐标。

支持：

- HTML：去除脚本、样式和明显站点布局，按原顺序提取标题、段落和表格；展开 `rowspan/colspan`。
- DOCX：按原顺序提取段落和表格；内嵌图片进入 OCR。
- XLSX/XLS：遍历全部 Sheet，展开合并单元格；超长 Sheet 每 500 行分块并重复表头。
- PDF：先在原生页级文本中识别完整且具有旋转、半透明或灰色视觉特征的强水印；仅当表格字符按原顺序能完整复原同一水印时，才在`table.extract()`前过滤这些字符。随后逐页提取文本块和表格；被表格区域覆盖的原生段落默认抑制，避免同一内容同时进入 paragraph/table；原生文本少于阈值的页自动进入 OCR。默认最多 OCR 20 页，`--max-ocr-pages-per-pdf 0` 可全量 OCR。
- JPG/PNG/TIFF：中文 OCR。
- ZIP/RAR：最多递归三层；校验路径穿越、符号链接、文件数、展开大小和 ZIP 压缩比；`.part1/.part2/...rar` 先完整落盘并归组，只从第一卷整体解压。
- TXT/JSON：分别转换为正文块和元数据块。
- 老版 DOC：优先调用 LibreOffice 转 DOCX；Windows 上可调用本机 Microsoft Word 隐藏转换。两者都不可用时明确生成 `error` block，不输出不可用于打标的 OLE 噪声。

文件按文件头识别，扩展名只作为兜底。任一附件失败会生成 `error` block，不阻塞同公告的其他内容。

## Block Schema

```json
{
  "schema_version": "1.1",
  "parser_version": "2.1.0",
  "parser_config_digest": "64位SHA-256",
  "parser_config": {"ocr": "rapidocr"},
  "notice_id": "20260814_27137567",
  "title": "满洲里海关技术中心2026年实验室仪器设备购置项目中标公告",
  "notice_metadata": {"region": "内蒙古"},
  "documents": [
    {
      "document_id": "f0001_12位哈希",
      "file_name": "公告.html",
      "container_path": "公告.html",
      "file_type": "html",
      "media_type": "text/html",
      "size_bytes": 12345,
      "sha256": "完整哈希",
      "status": "ok",
      "block_count": 12,
      "warnings": []
    }
  ],
  "blocks": [
    {
      "type": "table",
      "text": "| 货物名称 | 品牌 | 型号 |\n| --- | --- | --- |\n| 提取仪 | 恩计 | EJ1600 |",
      "source": {
        "document_id": "f0002_12位哈希",
        "file_name": "成交公示.docx",
        "container_path": "附件.zip/成交公示.docx",
        "file_type": "docx",
        "table_index": 1
      },
      "rows": [["货物名称", "品牌", "型号"], ["提取仪", "恩计", "EJ1600"]],
      "metadata": {"row_count": 2, "column_count": 3},
      "block_id": "20260814_27137567:blk_24位内容哈希"
    }
  ],
  "stats": {
    "document_count": 3,
    "block_count": 25,
    "document_status_counts": {"ok": 3},
    "block_type_counts": {"paragraph": 20, "table": 5},
    "ocr_backend": "rapidocr"
  }
}
```

`documents.status` 取值：`ok`（完整）、`partial`（已有内容但有降级或警告）、`unsupported`、`error`。Block ID 由公告 ID、稳定来源坐标和内容生成，不依赖全局遍历顺序；`parser_version + parser_config_digest` 用于判断两个产物能否直接比较。后续金标和银标都应使用 `block_id + source` 绑定证据。

机器可读的完整约束见 `docs/block_schema.json`。

## Aproject 环境

```powershell
conda activate Aproject
python -m pip install -r requirements-parsing.txt
```

本解析器不需要 PyTorch。OCR 默认使用轻量的 RapidOCR/ONNX；如暂不做 OCR，可传 `--ocr none`。老版 DOC/XLS 默认使用批处理更稳定的 LibreOffice。Windows 上若已安装 Word/Excel，可显式传 `--legacy-office-backend ms-office` 尝试只读、隐藏的 COM 转换；部分 Office 安装会拒绝无人值守保存，因此它是尽力而为的备选，失败详情会写入 `error` block。脚本只会在必要时强制关闭它自己创建的 Office 进程。RAR 使用系统 7-Zip，Windows 自带 `bsdtar` 为后备。

## 运行

先转换指定样例：

```powershell
conda run -n Aproject python scripts/parse_blocks.py `
  --ids 20260814_27137567 20260429_26479131 `
  --workers 1 --overwrite
```

批量转换：

```powershell
conda run -n Aproject python scripts/parse_blocks.py --workers 4
```

水印过滤默认开启。只有做新旧结果诊断比较时才使用`--no-pdf-watermark-filter`关闭；不要把关闭后的产物与默认产物混在同一目录。

默认输出：

- `dataset_build/blocks/notices/{notice_id}.json`：逐公告结果；
- `dataset_build/blocks/parse_report.json`：批处理汇总、失败公告和文档错误数。

重复运行默认跳过已有结果；需要重建时传 `--overwrite`。建议先跑少量样例检查报告，再全量转换。

最新代码是Parser 2.1.0，默认配置摘要为`f1a4cb0443b02b38af035bf43f26f97cc264315a2aba24d206a8525f5d0a5544`。当前`dataset_build/blocks/`尚未覆盖，仍是Parser 2.0.0的291/291篇全量产物：1,503个文档、274,597个Blocks，文档状态为`ok=1471 / partial=23 / error=2 / unsupported=7`，旧配置摘要为`61bfe1df950c6cd2a13ad44d5844382f9349151bfaa03f27fdab07147c17bcbc`。两个文档级error分别是关闭/加密PDF和LibreOffice无法转换的疑似老版DOC；七个unsupported主要是DWG、SXZB4和GEF。完整运行口径见根目录`block转化流程.md`。

水印处理的边界是“完整页级水印→表格字符级精确匹配”。不得在通用文本清洗或实体结果阶段按单个数字、字母、十六进制片段删除，否则会破坏型号后缀、`Q235`、尺寸、功率和参数编号。成功过滤的表格Block会记录`watermark_filtered`、`watermark_char_count`和`watermark_patterns`。

对金标候选做不截断的完整 OCR：

```powershell
conda run -n Aproject python scripts/parse_blocks.py `
  --ids 20260814_27137567 --max-ocr-pages-per-pdf 0 --overwrite
```

## 质量审计建议

解析成功不等同于内容正确。全量转换后至少检查：各类型 `error/partial` 比例、空 OCR 页、每篇表格数异常、文本长度异常、同一附件哈希重复，以及含“报价明细/主要标的信息”的文件是否产出了 table block。老版DOC转换失败时会直接进入错误报告；扫描PDF默认只OCR前20个扫描页，高价值结果附件位于后页时必须定向全页重跑。
