# 招采标讯实体挖掘与关系分析建模——项目总指导书

<<<<<<< Updated upstream
> 状态日期：2026-08-27。291篇外部API全量验证、任务一/二入库和任务三平台验收已经完成。新Codex会话先读`HANDOFF.md`；本轮数字以`run/full_api_20260827/FULL_PIPELINE_REPORT.md`和机器报告为准。
=======
> 状态日期：2026-09-03。页面展示为 v0.2 库（9B 批处理 + 4B 上传样本）+ Parser 2.1 Blocks。上传流水线已接通，运行时本地模型为 LM Studio `qwen/qwen3-4b-2507`。前端展示与交互已按现有主视觉优化（导入任务简介、检索表规格、图谱静力布局）。v0.1 API 全量数字仍以`run/full_api_20260827/FULL_PIPELINE_REPORT.md`为准；v0.2 9B 质量见`run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md`；上传样本见`run/v0.2_local_20260828/PIPELINE_SAMPLES.md`。新会话先读`HANDOFF.md`。
>>>>>>> Stashed changes

## 1. 项目目标

本项目对应“中国电子杯”第三届“四邮四电”高校ICT产教融合创新大赛中国软件命题，目标是构建一个可离线部署的招采标讯分析系统：

1. 从公告HTML和ZIP附件中抽取标的物的产品/服务名称、品目、品牌或产品供应商、规格型号、单价、数量、总价；
2. 从公告中的采购单位、中标供应商、投标参与方、报价、得分和审查结果构建关系模型，并实现五个指定分析场景；
3. 通过Vue + Python平台完成批量输入、自动处理、检索、导出、统计和关系图展示。

赛题评分重点是任务一覆盖率、字段提取率、准确性和速度，任务二五个场景，任务三功能完整性、技术栈和查询速度，以及最终文档与演示质量。

## 2. 当前总状态

| 模块 | 当前代码 | 当前产物 | 状态结论 |
|---|---|---|---|
| 原始数据 | 抓取、修复、同步、审计脚本 | 291篇HTML、243个附件ZIP | 自建开发集可用 |
| Block解析 | Parser 2.1.0 / Schema 1.1 | 正式目录仍为Parser 2.0.0：291篇、1,503文档、274,597 Blocks | 原生PDF水印过滤已完成真实单PDF回归，待隔离全量重跑 |
| 本地筛选 | Selector 1.3.0 | 291篇、3,716来源Blocks、1,411请求 | 全量重跑完成，完整性错误0，金标证据召回100% |
| 人工金标 | 标注构建与强校验脚本 | 20篇、128条 | 单人金标种子，未双人复核 |
| API银标 | DeepSeek few-shot打标工具 | 116篇、2,315条 | 已完成并校验，但只对原始10篇金标回归 |
| 任务一智能体 | LangGraph Agent 2.1.0 | 291篇、1,411请求、3,552实体 | 外部API全量闭环完成；本地模型同口径回归待做 |
| 时序联网核验 | Verifier 1.0.0 | 1个“新华三”真实小样本 | 工程可用，DDGS证据不等于权威登记 |
| 任务二 | Relation Agent 1.4.0 + SQLite | 291项目、303包件、563竞标关系 | 外部API全量结构/证据验收完成；无人工关系金标 |
| 任务三 | FastAPI + Vue 3 + SQLite | 隔离库3,552实体、291关系项目 | 检索/证据/导出/五场景/图谱全量通过；上传自动抽取未接通 |
| 本地模型 | OpenAI兼容本地后端接口 | `models/llm/`为空 | llama.cpp和GGUF尚未落盘/实测 |
| 自动化测试 | pytest + Vue生产构建 | 58项pytest、compileall、Vue构建通过 | 仍缺多轮并发P95和本地模型效果测试 |

注意：必须区分“代码已经升级”和“默认数据目录已经用新代码重跑”。目前Selector与Agent都存在这种版本差异。

## 3. 当前整体架构

```text
原始HTML + 同公告附件ZIP
  → 多格式识别与安全递归解包
  → Parser 2.1统一Blocks（文本、表格、OCR、来源坐标、水印过滤）
  → Selector 1.3本地相关证据筛选与分块
  → LangGraph任务一抽取图
       ├─ 强结构化表：受限规则快速通道
       └─ 弱表/正文：外部API或本地OpenAI兼容模型
  → Schema、Block行、金额一致性校验与最多一次修复
  → 公告级去重、冲突保留、证据合并
  → 可选公司/品牌时序联网核验子图
  → 任务一JSON/JSONL → SQLite → 检索/证据/导出

同一批Blocks
  → 任务二规则候选
  → 受控关系智能体 + 本地模型
  → Pydantic与证据回指校验
  → SQLite关系权威表 + 六张预计算表
  → 五个业务场景与项目子图

FastAPI
  → 单端口托管Vue构建产物
  → 数据导入、任务状态、任务一检索、任务二场景、ECharts图谱
```

## 4. 技术栈

### 4.1 已经实际使用

| 层级 | 技术 |
|---|---|
| Python环境 | Conda `Aproject`，Python 3.11 |
| 文档解析 | lxml、python-docx、openpyxl、xlrd、PyMuPDF、Pillow |
| OCR | RapidOCR + ONNX Runtime |
| 老版Office | 项目内LibreOffice 26.2.5 headless |
| 智能体 | LangGraph 1.x、OpenAI兼容Chat接口、Pydantic v2 |
| 小样本搜索 | DDGS，可替换Replay或其他provider |
| 业务存储 | SQLite WAL、索引、预计算表 |
| 后端 | FastAPI、Uvicorn |
| 前端 | Vue 3、TypeScript、Vite、Vue Router、ECharts |
| 导出 | CSV、openpyxl XLSX |
| 测试 | pytest、FastAPI TestClient、Vue TypeScript检查与Vite build |

### 4.2 已预留但尚未实测

- 本地Qwen GGUF + llama.cpp或任何OpenAI兼容本地服务；
- 不支持原生tool calling时的`deterministic`联网核验模式；
- 官方工商、商标或商业企业数据接口；
- Neo4j/Kuzu展示后端；
- NER/UIE、品目词典、向量few-shot召回、轻量微调。

这些不是当前可用系统的前置依赖。只有真实评测证明现有方案不足时才引入，避免在2GB显存和比赛现场环境中增加故障点。

## 5. 数据与版本契约

### 5.1 原始数据

```text
dataset_build/mirror_task1/notices/<notice_id>.html
dataset_build/mirror_task1/attachments/<notice_id>.zip
dataset_build/mirror_task2/notices/<notice_id>.html
dataset_build/manifests/manifest.json
```

官方数据发布后应编写`official_adapter.py`，只把官方目录映射成上述同构输入，不改核心流水线。

### 5.2 Block契约

最新代码Parser 2.1.0把公告HTML和所有递归附件整合进一个公告JSON。表格保留二维`rows`和Markdown `text`；所有Block包含`source`。Block ID为稳定来源与内容哈希，不依赖全局顺序。2.1.0新增PDF原生水印过滤，默认配置摘要为：

```text
f1a4cb0443b02b38af035bf43f26f97cc264315a2aba24d206a8525f5d0a5544
```

当前`dataset_build/blocks/`尚未覆盖，仍是Parser 2.0.0全量产物，其配置摘要为：

```text
61bfe1df950c6cd2a13ad44d5844382f9349151bfaa03f27fdab07147c17bcbc
```

详细流程见`block转化流程.md`和`docs/BLOCK_PARSER.md`。

### 5.3 标注和输出字段

概念上仍是赛题七类字段；工程Schema将品目和数量拆开：

```text
product_service_name
category_name
category_code
brand_supplier
spec_model
unit_price
quantity
quantity_unit
total_price
evidence_refs
```

缺少原文证据必须为`null`。金额统一为元；不能把中标供应商自动当作产品品牌；采购需求、预算、限价、空模板和评分办法不能当实际中标结果。

## 6. 任务一：实体识别

### 6.1 Block解析

已支持HTML、DOC/DOCX、XLS/XLSX、PDF、图片、TXT、JSON、ZIP和RAR。实现了：

- 文件头识别；
- 压缩包路径穿越、符号链接、文件数、展开体积和压缩比防护；
- 分卷RAR归组；
- LibreOffice老格式转换；
- PDF扫描页OCR；
- PDF表格与段落重叠抑制；
- 在PDF页级识别完整、旋转/半透明/灰色的强水印，再于`table.extract()`前删除能完整复原同一水印的字符序列；
- 单文件失败隔离；
- 稳定Block ID和解析配置摘要。

水印过滤不在`clean_text()`或实体字段阶段删除零散数字/字母，因此不会按形态误删`JSGS01`、`Q235`或`DS-2CD3T26WDA4-L`。真实文件`20241217_23892691/分项报价表.pdf`回归中，16张表移除16×50个水印字符，合法型号和参数全部保留；正式Block和下游结果尚未重跑。

### 6.2 本地筛选

Selector使用文件名、表头、关键词、金额数量特征、PDF续表继承和正文邻域，在本地生成可直接供模型使用的请求JSON。它不调用API。

代码和默认全量`dataset_build/model_inputs/`均为1.3.0。291篇从274,597个Blocks筛到3,716个来源Blocks，生成1,411个请求，压缩率98.65%；20篇金标范围的22个来源Block、127个唯一证据行召回100%。

### 6.3 LangGraph受控抽取

主图状态：

```text
prepare
  → route
  → rule_extract 或 model_extract
  → validate
  → repair（最多一次）
  → accept / reject / needs_model
```

强表规则快速通道只在可靠表头映射和足够产品信号同时成立时使用；它不是规则包打天下。正文、弱表和复杂情况交给模型。模型输出必须通过真实Block ID、表格行号、可映射列和金额关系校验。

`confidence`目前是固定质量档位，不是由金标校准的正确概率。需要召回优先测试时使用`--keep-covered-text`，避免高分强表导致正文被覆盖跳过。

### 6.4 联网时序核验

联网核验在公告级实体合并后执行，只验证`brand_supplier`候选在公告日期附近是否存在、是否为历史别名、是否发生时代错位或品牌/公司混淆。结果通过`external_verification_id`关联，不覆盖公告原文。

工具模式：

- `auto/model`：模型使用原生tool calling规划搜索；
- `deterministic`：本地控制器生成受限查询，模型只总结搜索证据，适配不支持工具调用的本地模型。

所有非证据不足结论引用的URL必须真实来自本次搜索结果。DDGS只是小样本搜索源，低等级来源强制人工复核，不能替代工商或商标登记。

### 6.5 当前任务一产物

- 金标：20篇128条，全部通过证据和金额校验，仍是单标注员；
- 银标：116篇2,315条，DeepSeek API生成并校验；
- 旧全量规则基线：291篇、1,265请求、4,440实体，仅保留作历史对照；
- Agent 2.1外部API全量：291篇、1,411请求全部成功、3,552实体；历史708次调用、1,227,898 Token；
- 20篇128条单人金标：证据召回100%，严格全字段一致87.5%，字段一致率94.53%–100%；
- 强表+联网核验样本：规则抽取0次模型，核验2次调用、4,852 Token；
- 4篇Codex人工响应Replay闭环：8条任务一实体，但不代表模型效果。

## 7. 任务二：关系分析

当前使用“规则候选 + 受控模型判断 + 强Schema/证据校验 + SQLite”的流程。没有模型时只输出`candidate_only`，不会默认写入权威关系库。

关系对象包括项目、采购单位、代理机构、包件、中标供应商、投标参与方、报价、得分、排名、资格/符合性审查结果以及产品。

SQLite维护原始关系表和六张预计算表，实现：

1. 采购单位的长期/大量合作中标供应商；
2. 采购单位的TOP投标主体及高频共同投标组合；
3. 中标供应商的高频共同竞标主体；
4. 多个供应商共同合作的采购单位；
5. 多个供应商共同参与的历史项目和结果。

已通过合成契约测试和4篇隔离Replay闭环。正式`application.db`中的任务二表仍为空，尚无真实本地模型准确率、200篇抽检和五场景人工断言。

详见`docs/TASK2_RELATION_SYSTEM.md`。

## 8. 任务三：本地平台

FastAPI单端口托管Vue生产构建，SQLite保存任务一实体、处理任务和任务二关系。

已实现：

- 批量上传和文件暂存；
- 任务详情、状态和SSE；
- 任务一字段检索、分页、详情、Block证据回读、CSV/XLSX全量导出；
- 任务二五场景页面与图表；
<<<<<<< Updated upstream
- 按项目投影关系子图；
- 系统状态页；
- 空库和模型未配置的真实状态。
=======
- 按项目投影关系子图（分层静力布局，节点可拖拽、无弹力回拉）；
- 系统状态页（本地模型名来自 `config/llm_config.yaml`）。
- 导入页随任务一/二切换展示简介、字段和处理流程；检索表固定列宽、行高和滚动区高度。
>>>>>>> Stashed changes

尚未实现上传后的自动Parser → Selector → Agent → 入库编排。正式库当前有4,440条旧规则实体，任务二为空；4篇pilot使用独立数据库，不污染正式库。

详见`docs/TASK3_PLATFORM.md`。

## 9. 模型与API策略

开发阶段允许使用OpenAI兼容外部API进行小样本验证、银标和提示词迭代；最终比赛系统目标是离线本地模型。

所有外部API调用必须满足：

- 密钥只从环境变量或`.env`读取；
- 命令显式包含`--allow-external-api`；
- 设置正数`--max-model-calls`和Token硬上限；
- 首先指定`--request-id`跑小样本；
- 输出记录实际调用数和Token；
- API余额不足时不得扩大样本。

当前密钥曾在对话中明文出现，应轮换。新会话不得在文档、日志或工具输出中重复密钥。

本地模型接入只需启动OpenAI兼容服务并使用`--backend local`。模型目录目前为空，不能把“后端代码存在”写成“本地模型已经部署完成”。

## 10. 运行入口

### 10.1 Block解析

```powershell
conda run -n Aproject python scripts/parse_blocks.py --workers 4
```

### 10.2 Selector

```powershell
conda run -n Aproject python scripts/select_blocks.py --overwrite
```

### 10.3 任务一离线规则基线

```powershell
conda run -n Aproject python scripts/run_entity_agent.py --backend rules
```

### 10.4 任务一本地模型

```powershell
conda run -n Aproject python scripts/run_entity_agent.py `
  --backend local `
  --keep-covered-text
```

### 10.5 任务二候选和本地模型

```powershell
conda run -n Aproject python scripts/run_relation_agent.py --backend rules --limit 20
conda run -n Aproject python scripts/run_relation_agent.py --backend local --commit
```

### 10.6 平台

改前端页面时用双进程（Vite 热更新）。浏览器打开 `http://127.0.0.1:5173/`：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm.cmd run dev
```

演示或验收生产形态时再构建并单端口托管：

```powershell
cd frontend
npm run build
cd ..
conda run -n Aproject python scripts/init_app_db.py --import-task1
conda run -n Aproject python scripts/run_server.py
```

<<<<<<< Updated upstream
=======
访问 `http://127.0.0.1:8000/`。默认读 v0.2 库和 Parser 2.1 Blocks，上传走本地 4B。切回 v0.1：`--db run/data/full_api_20260827.db --block-dir dataset_build/blocks/notices`。仅规则通道：`--pipeline-backend rules`。不要对冻结库重跑 `init_app_db.py`。完整命令表见 `HANDOFF.md`。

>>>>>>> Stashed changes
## 11. 测试与效果口径

当前自动化检查：

```powershell
conda run -n Aproject python -m pytest -q
conda run -n Aproject python -m compileall -q src scripts
cd frontend
npm run build
```

最近一次pytest为58项全部通过，`compileall`和Vue生产构建通过。291篇全量平台验收报告位于`run/full_api_20260827/platform_verification.json`；4篇Replay pilot仍保留作离线回放：

```powershell
conda run -n Aproject python scripts/verify_model_substitute_pilot.py
```

以下数字不能当正式准确率：

- 原始10篇金标上的90/90银标或旧规则回归；
- 4篇Codex人工响应Replay结果；
- 1条重叠金标100%；
- 8实体/4项目小库的毫秒级延迟。

正式结论需要独立双人金标、真实本地模型输出、字段级P/R/F1、失败率、固定机器上的单篇耗时，以及真实规模P50/P95。

## 12. 当前风险

1. 本地GGUF和推理服务未落盘，最终离线闭环未验证；
2. 外部API全量已经完成，但最终本地模型尚未对291篇同口径重跑；
3. 金标只有20篇且全部单人标注，格式和业务分布仍不充分；
4. 两个文档解析error、七个专业格式unsupported，长扫描PDF还有20页OCR上限；正式Block仍为Parser 2.0.0，尚未应用2.1.0水印过滤；
5. 规则快速通道置信度未校准，高置信强表可能遮蔽正文；
6. `brand_supplier`同时容纳品牌、制造商和产品供应商，联网前实体类型仍可能混淆；
7. DDGS不能替代权威企业登记，时序结论可能受搜索噪声和未来页面影响；
8. 任务二291篇已通过结构和证据审计，但没有人工关系金标，不能报告真实准确率；
9. 平台上传只暂存，尚未调度完整抽取流水线；
10. 当前目录没有Git仓库，缺少可靠变更回滚和版本审计；
11. API密钥曾在对话中暴露，必须轮换并继续只用环境变量；
12. Vue生产构建通过，但ECharts关系图分包约508KB并触发Vite体积警告；目前不影响功能，正式演示前可按需动态加载或拆包。

## 13. 推荐实施顺序

<<<<<<< Updated upstream
1. 轮换API密钥，确认本地模型文件、许可、校验和及OpenAI兼容服务能启动；
2. 在隔离目录用Parser 2.1.0重跑Blocks，比较受水印影响的公告；该步骤完全本地，不调用API；
3. 对内容或Block ID变化的公告重跑Selector，并迁移受影响的金标证据引用；
4. 使用与Parser版本一致的请求和20篇金标对本地模型做同口径回归，再逐级扩大到291篇；
5. 根据金标错误调整提示词、Selector或校验器，记录字段级指标和耗时；
6. 用Agent 2.1本地后端断点跑全量，并导入新的隔离数据库；旧Selector请求不能直接视为Parser 2.1.0证据；
7. 为任务二准备含投标、得分、排名和审查表的人工关系金标，完成字段级评估；
8. 把平台上传任务接到Parser → Selector → Agent → SQLite，完成失败重试和状态进度；
9. 扩充并双人复核金标，补正式准确率、速率和查询P95；
10. 编写官方数据适配器；
11. 最后整理离线依赖、一键启动、设计文档、PPT、双视频和提交包。
=======
1. 轮换API密钥；不要重复已成功的外部API全量；
2. 前端展示优化已完成，不要再把改版式列为下一步；改 Vue 用 Vite `5173` + 后端 `8000`；
3. 优化任务一提示词/校验：`category_code`、弱表/正文漏抽；用20篇金标做同口径回归；
4. 隔离补跑剩余空实体与任务二失败篇，写新目录，成功后再选择性入库；
5. 为任务二准备含投标、得分、排名和审查表的人工关系金标，完成字段级评估；
6. 扩充并双人复核金标，补正式准确率、速率和查询P95；
7. 编写官方数据适配器；
8. 若赛题最终要求自带GGUF，再落盘llama.cpp并做同口径回归；
9. 最后整理离线依赖、一键启动、设计文档、PPT、双视频和提交包。

Parser 2.1 隔离全量、上传流水线和前端展示优化已经完成，不要再把它们列为下一步。
>>>>>>> Stashed changes

## 14. 文档入口

- 新会话交接：`HANDOFF.md`
- 文档职责：`docs/README.md`
- Block运行流程：`block转化流程.md`
- Block技术契约：`docs/BLOCK_PARSER.md`
- Selector：`docs/MODEL_INPUT_SELECTOR.md`
- 任务一Agent：`docs/ENTITY_EXTRACTION_AGENT.md`
- 任务二：`docs/TASK2_RELATION_SYSTEM.md`
- 任务三：`docs/TASK3_PLATFORM.md`
- 4篇隔离闭环：`dataset_build/pilot/model_substitute_20260826/README.md`
- 291篇全量验收：`run/full_api_20260827/FULL_PIPELINE_REPORT.md`
