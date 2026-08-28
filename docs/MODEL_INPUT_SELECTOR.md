# Block 本地筛选与大模型输入生成

## 目标

该步骤位于统一 Block 解析和大模型实体抽取之间，完全在本地执行，不调用 API：

```text
公告 Block JSON
→ 文件名/表头/关键词/金额数量特征评分
→ 表格行切分、相关段落邻域扩展
→ OpenAI 兼容 api_payload
```

实现入口：

- 核心逻辑：`src/extraction/block_selector.py`
- 批处理命令：`scripts/select_blocks.py`
- 单元测试：`tests/unit/test_block_selector.py`

## 默认运行

```powershell
$env:PYTHONIOENCODING='utf-8'
conda run -n Aproject python scripts/select_blocks.py --overwrite
```

只处理指定公告：

```powershell
conda run -n Aproject python scripts/select_blocks.py `
  --ids 20260813_27128600 20260814_27137567 --overwrite
```

## 输出

```text
dataset_build/model_inputs/
├─ notices/<notice_id>.json       # 公告级筛选结果和全部请求包
├─ api_requests.jsonl             # 每行一个可直接调用的请求
├─ model_input_schema.json
├─ selection_report.json
└─ selection_report.md
```

`api_requests.jsonl` 每行包含：

```json
{
  "notice_id": "20260813_27128600",
  "request_id": "20260813_27128600:req_001",
  "content_kind": "table",
  "source_block_ids": ["20260813_27128600:blk_xxx"],
  "api_payload": {
    "messages": [
      {"role": "system", "content": "实体抽取约束提示词"},
      {"role": "user", "content": "带block_id和行号的证据JSON"}
    ],
    "temperature": 0,
    "response_format": {"type": "json_object"}
  }
}
```

调用 OpenAI 兼容接口时只需补充模型名：

```python
response = client.chat.completions.create(
    model=model_name,
    **record["api_payload"],
)
```

## 筛选规则

1. 表格：检查前12行，识别产品/服务名称、品目、品牌、型号、单价、数量和总价表头；结合真实数据行、金额和附件文件名评分。
2. 正文/OCR：使用“主要标的信息、分项报价、中标、成交、品牌、型号、单价、数量、金额”等特征评分，保留命中段落前后默认2个 Block。
3. PDF续表：同一PDF后页缺少表头时，从最近的同列结构强表头继承字段；后页第一条产品从 `block_row=1` 开始保留，不再误当表头。允许PDF续页比首页少1～2个空备注列。
4. 弱结构表格：单单元格HTML表、纵向键值表及无法可靠确认表头的表格按正文证据发送，避免为了结构化而误删第一条产品。
5. 长表格和长文本：表格默认每40个有效行生成一次请求；长正文按字符预算拆分，均保留原 `block_id`、表格行号或字符区间。
6. 多包件：最多选择8个不同文件/Sheet来源；PDF页不再单独占用来源名额，同一入选PDF的所有相关续页均可保留。当前真实数据每篇最多6个表格来源，未触发截断。
7. 重复证据：根据标准化表头、数据行或正文生成内容摘要，删除完全重复请求；较长来源词已命中时不再重复累计其子串分数，如“分项报价”不再叠加“报价”。
8. 请求顺序：筛选时按相关性决定来源是否入选，输出时恢复原文件/页顺序，便于跨页结果合并。
9. 无强候选时：使用最高分文本作为兜底；没有任何相关证据时允许输出0个请求，避免无意义API调用。

## 当前代码与产物版本

当前代码版本为Selector `1.3.0`。它已在20篇、128条金标范围内验证：22个来源Block和127个唯一证据行召回均为100%，对应产物位于`dataset_build/gold/expansion_20260826/model_inputs_all_gold/`。

但是默认全量目录`dataset_build/model_inputs/`仍是Selector `1.1.0`产物，尚未用1.3.0覆盖重跑。该历史全量结果为：

- 原始 Blocks：274,597；
- 入选来源 Blocks：3,572；
- Block 压缩率：98.70%；
- API请求包：1,265；
- 其中跨页继承表头表格：271；去除完全重复请求：13；
- 无候选公告：0；
- 当时10篇金标的来源Block召回率：100%；
- 当时90个金标证据行召回率：100%；
- 6,662个表格证据行、正文字符区间和全部请求引用的完整性错误：0。

下一步应先执行`select_blocks.py --overwrite`，生成291篇Selector 1.3.0全量产物并重新记录请求数、压缩率、20篇金标召回和完整性检查。完成之前，不应把上述1.1.0请求统计描述成当前代码的最终输出。

金标召回率只说明“已标注证据没有被筛掉”，不等同于全量实体抽取准确率。后续仍需对 API 返回运行字段校验、来源回指、金额一致性检查以及跨请求合并去重。
