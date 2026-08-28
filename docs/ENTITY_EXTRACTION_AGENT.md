# 任务一：LangGraph 受控实体抽取与联网时序核验

## 1. 当前定位

任务一不再是“每个筛选请求直接调用一次 API”，也不是允许模型任意行动的开放式 Agent。当前实现由两张 LangGraph 状态图组成：

```text
抽取图：筛选请求 → 解析 → 路由 → 规则/模型 → 校验 → 最多一次修复 → 结果
核验图：公告级实体 → 模型或控制器生成查询 → web_search工具 → 强制收尾 → URL回指校验 → 结果
```

模型负责提出候选实体或外部核验结论；本地代码负责状态转移、工具权限、真实 Block/URL 回指、金额检查、调用上限、重试次数、断点和持久化。最终本地部署时仍使用同一状态图，只把 OpenAI 兼容后端从外部 API 切换到本地服务。

默认 `rules` 后端完全离线，不读 Key、不访问网络、不产生模型费用。无法安全规则抽取的请求标记为 `needs_model`。

## 2. 实现位置

| 文件 | 职责 |
|---|---|
| `src/agents/entity_extraction_agent.py` | LangGraph 抽取图：解析、路由、规则/模型、校验和有限修复 |
| `src/agents/verification/temporal_agent.py` | LangGraph 联网核验图和 ToolNode |
| `src/agents/verification/providers.py` | DDGS、回放、持久缓存等可替换搜索提供方 |
| `src/agents/verification/schemas.py` | 公司/品牌时序核验严格 Schema |
| `src/agents/tools.py` | 强表抽取、数值/数量/品目处理和证据来源定位 |
| `src/agents/validators.py` | 实体 JSON、真实 Block/行和金额一致性校验 |
| `src/agents/backends.py` | Fake、Replay、外部/本地 OpenAI 兼容后端及调用硬预算 |
| `src/agents/merger.py` | 公告级去重、同证据字段补充和冲突保留 |
| `scripts/run_entity_agent.py` | CLI、请求筛选、断点、公告合并、联网核验和报告 |
| `requirements-agents.txt` | LangGraph、OpenAI兼容客户端和试验搜索依赖 |

## 3. 抽取状态图

```text
START
  → prepare
  → [强结构化表] rule_extract ───────────────→ END
  → [弱表/正文 + 有模型] model_extract
       → validate
       → [硬错误且允许] repair（最多一次）
       → accept_model / reject_model
  → [弱表/正文 + 无模型] defer(needs_model)
```

抽取图保留原有行为：

- 表格必须映射出产品/服务名称和至少两个产品信号才可走规则快速通道；
- 模型不能伪造 `block_id` 或表格 `block_row`；
- 表格未映射列对应的模型字段会被清空；
- `单价×数量` 与总价按配置容差检查；
- 错误最多修复一次，warning 不自动触发修复；
- `workflow_trace`、`confidence_basis` 和用量写入请求状态；
- 断点键包含 Agent 配置和请求内容摘要，Selector 或 evidence 变化后不会错误复用旧结果。

注意：当前 `confidence` 仍是固定质量档位，不是经金标校准的正确概率。强表 `0.94` 仍可能触发公告正文跳过；召回优先测试应增加 `--keep-covered-text`，纯模型对照使用 `--model-only`。

## 4. 联网时序核验状态图

联网核验发生在公告级合并之后，只处理去重后的 `brand_supplier` 候选，不改变公告原始抽取值。

```text
START
  → verification_model
  → web_search ToolNode（受查询数/轮次限制）
  → verification_model（达到限制后自动禁用工具并强制JSON）
  → validate_verification
  → [可选] request_verification_repair
  → END
```

主要约束：

- 网页文本始终视为不可信证据，不能成为指令；
- 除 `insufficient_evidence` 外，模型引用的 URL 必须真实来自本次搜索工具；
- 当前日期来自公告 ID 的 `YYYYMMDD` 前缀，并显式记录 `as_of_date_source`；
- 搜不到不能判定不存在；低等级来源保留结论但强制 `review_required=true`；
- 搜索结果持久缓存，成功核验按 Agent/提供方/配置/候选/日期断点复用；
- 当前 DDGS 只是无 Key 的小样本提供方，后续可替换为 Tavily、Exa、MCP、企业数据接口或官方数据源适配器。

核验状态包括：精确存在、品牌存在、历史别名、时代错位、品牌/公司混淆、证据冲突和证据不足。结果与实体通过 `external_verification_id` 关联，不覆盖 `brand_supplier` 原文。

联网核验有三种工具模式：

- `auto`：默认模式，优先让模型按原生 tool calling 协议规划搜索；
- `model`：明确要求模型原生调用工具，适合已验证支持工具调用的服务；
- `deterministic`：由本地控制器根据候选名称和公告日期生成有限查询，模型只读取搜索结果并输出核验 JSON。它不要求本地模型支持原生 tool calling，仍保留搜索次数、真实 URL 回指和来源质量约束。

## 5. 安装

```powershell
conda run -n Aproject python -m pip install -r requirements-agents.txt
```

已验证环境：Python 3.11、LangGraph 1.2.11、DDGS 9.15.0。

## 6. 运行方式

### 6.1 纯规则离线基线

```powershell
conda run -n Aproject python scripts/run_entity_agent.py --backend rules
```

### 6.2 最终本地模型

先启动 `config/llm_config.yaml` 中 `local.server_url` 对应的 OpenAI 兼容服务，再运行。当前本地配置指向 LM Studio `http://127.0.0.1:1234`、模型 `qwen/qwen3-4b-2507`（非 thinking）。校验器仍会剥离 `<think>` 痕迹后再解析 JSON。小样本必须设置 `--max-model-calls` 和 `--max-total-tokens`，输出目录不得覆盖外部 API 参考结果：

```powershell
conda run -n Aproject python scripts/run_entity_agent.py `
  --backend local `
  --model-only `
  --max-model-calls 2 `
  --max-total-tokens 24000 `
  --request-id 20260813_27128600:req_001 `
  --output run/local_lmstudio_20260828/gold1_instruct_probe
```

仓库当前没有内置 GGUF；LM Studio 等 OpenAI 兼容服务按 `config/llm_config.yaml` 的 `local` 段接入。如果本地模型不支持原生 tool calling，抽取图仍可运行；启用联网核验时追加 `--verification-tool-mode deterministic`，由控制器生成搜索查询，模型只负责根据检索证据生成严格 JSON。

```powershell
conda run -n Aproject python scripts/run_entity_agent.py `
  --backend local `
  --verify-web `
  --allow-web-search `
  --verification-tool-mode deterministic `
  --verify-max-entities 1 `
  --verify-max-search-rounds 1 `
  --verify-max-search-queries 2
```

### 6.3 外部 API 小样本抽取

API 后端必须同时显式授权并设置正数调用硬上限：

```powershell
conda run -n Aproject python scripts/run_entity_agent.py `
  --backend api `
  --allow-external-api `
  --max-model-calls 2 `
  --max-total-tokens 5000 `
  --request-id <request_id>
```

Key 只从配置指定环境变量或项目 `.env` 读取，不写入结果和日志。`--request-id` 可重复，用于精确选择小样本。

### 6.4 外部 API + 联网时序核验

```powershell
conda run -n Aproject python scripts/run_entity_agent.py `
  --backend api `
  --allow-external-api `
  --max-model-calls 3 `
  --max-total-tokens 8000 `
  --verify-web `
  --allow-web-search `
  --search-provider ddgs `
  --verification-tool-mode auto `
  --verify-max-entities 1 `
  --verify-max-search-rounds 1 `
  --verify-max-search-queries 2 `
  --request-id <request_id>
```

API 调用上限由抽取图和核验图共享。达到上限会在下一次调用前抛出受控错误，不会继续消费余额。

## 7. 输出

```text
<output>/
├─ notices/<notice_id>.json
├─ agent_items.jsonl
├─ agent_manifest.json
├─ agent_report.md
├─ agent_state.jsonl
├─ verification_state.jsonl
└─ verification_search_cache.jsonl
```

`agent_manifest.json` 分别记录：

- 抽取用量 `usage`；
- 核验用量 `verification.usage`；
- 总用量 `combined_usage`；
- 实际硬预算计数 `model_budget`。

估算费用只有在配置中填写模型单价后才有意义；当前 DeepSeek 配置未填写单价，因此报告为 0 元不代表真实免费，应以 Token 和服务商账单为准。

## 8. 真实小样本测试（2026-08）

### 291篇外部API全量验证

2026-08-27已完成Selector 1.3 + Agent 2.1全量闭环：

- 291篇公告、1,411个请求全部成功，最终3,552条实体；
- 272个规则抽取、208个强表覆盖、463个模型结果、2个模型修复、465个非结果证据本地过滤、1个超长OCR分块恢复；
- 历史API用量708次调用、1,227,898 Token；
- 3,552个主Block引用和4,085个补充证据引用全部有效；
- 20篇128条单人金标证据召回100%、严格全字段一致87.5%、字段一致率94.53%–100%。

最终结果为`run/full_api_20260827/agent2_curated/`，详细报告见`run/full_api_20260827/FULL_PIPELINE_REPORT.md`。这些结果验证外部API工程路线；最终本地GGUF仍需按同一请求和金标回归。

### 正文模型抽取

- 请求：`20260815_27141077:req_001`；
- 输入为 167 字正文；
- 1 次 DeepSeek 调用，1,190 Token；
- 得到：挂壁式空调 / TCL / KFR-35GWAF21+B1 / 150台 / 单价1800元 / 总价270000元；
- Block 回指和金额一致性通过；状态为 `success/model`。

### 强表规则抽取 + 联网核验

- 请求：`20260814_27138537:req_001`；
- 规则得到：存储服务器 / 新华三 / H3C UniServer R4930 G7 / 3套 / 单价390000元；
- 抽取阶段 0 次模型调用；
- 核验阶段 2 次 DeepSeek 调用、4,852 Token、2 个搜索查询；
- 输出 `verified_exact_at_date`，引用 URL 均通过本地回指；
- 搜索结果包含新华三官网、百科和新闻，但没有政府/监管来源，所以最终为 `evidence_quality=low`、`review_required=true`，不能作为权威企业登记确认。

本节早期小样本阶段累计发生10次API调用、23,993 Token，其中暴露并修复了“达到搜索上限后仍请求工具”和“模型未看到明确核验Schema”两个问题。后续291篇全量用量以本节前面的全量验证统计为准。

## 9. 当前状态边界

- 当前Selector代码和`dataset_build/model_inputs/`全量产物均为1.3.0；完整性错误为0；
- `run/full_api_20260827/agent2_curated/`是当前Agent 2.1外部API全量权威产物；旧`dataset_build/agent_results/`只作规则基线对照；
- 当前正式金标为20篇128条，仍是单人标注种子，没有双人复核，不能代表291篇全量准确率；
- 新LangGraph实现已完成291篇全量工程验证，但本地模型尚未完成同口径效果和速度测试；
- DDGS 不是企业登记数据库，官方工商、商标和商业企业数据接口仍待接入；
- 当前只有条目级 Block 证据和外部 URL 证据，没有逐字段网页证据；
- `brand_supplier` 同时容纳品牌、制造商和产品供应商，联网核验前的实体类型分类仍需更多金标评估；
- 本地模型尚未准备完成，抽取质量、速度以及 `model`/`deterministic` 两种联网核验模式的实际效果仍待实测。
