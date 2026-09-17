# Codex项目交接文档

<<<<<<< Updated upstream
> 交接日期：2026-08-27  
> 工作区：`D:\all_contest\2026_8_15`  
> Python：Conda `Aproject`，Python 3.11  
> 当前权威报告：`run/full_api_20260827/FULL_PIPELINE_REPORT.md`  
> 最近验证：58项pytest、`compileall`、Vue生产构建和291篇平台验收全部通过

## 接手后先做什么

1. 先读本文，再读`PROJECT_GUIDE.md`和当前模块的`docs/*.md`；
2. 查看`run/full_api_20260827/FULL_PIPELINE_REPORT.md`与`platform_verification.json`，不要引用旧规则基线作为现状；
3. 不要读取、打印、复制或提交`.env`；旧API密钥曾在对话中暴露，应由用户轮换；
4. 默认不再调用外部API。若用户再次明确授权，必须同时设置调用次数和Token硬上限；
5. 不覆盖旧结果目录和`run/data/application.db`；当前全量隔离库是`run/data/full_api_20260827.db`；
6. 当前目录不是Git仓库，不能依赖`git diff`、分支或回滚。
=======
> 交接日期：2026-09-03  
> 工作区：`D:\all_contest\2026_8_15_proc-bid-ner`（Git 仓库）  
> Python：Conda `Aproject`，Python 3.11  
> 当前页面：v0.2 库 `run/data/v0.2_local_20260828.db` + Parser 2.1 Blocks `run/parser_2_1_20260828/notices`  
> 上传流水线：已接通（`src/api/pipeline.py`），默认 `--pipeline-backend local`  
> 运行时本地模型：LM Studio `qwen/qwen3-4b-2507` @ `http://127.0.0.1:1234`，上下文 32768  
> 前端：2026-09-03 已完成展示与交互优化（导入任务简介、检索表规格、图谱静力布局）；改页面请走 Vite `5173` + 后端 `8000`  
> v0.1 冻结库：`run/data/full_api_20260827.db`（不要覆盖）  
> 质量说明：`run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md`  
> 流水线样本：`run/v0.2_local_20260828/PIPELINE_SAMPLES.md`

## 接手后先做什么

1. 先读本文，再读 `PROJECT_GUIDE.md` 和当前模块的 `docs/*.md`；
2. 页面默认读 v0.2 库。v0.1 API 全量事实仍以 `run/full_api_20260827/FULL_PIPELINE_REPORT.md` 为准；v0.2 9B 批处理以 `QUALITY_AND_DISPLAY.md` 为准；上传闭环以 `PIPELINE_SAMPLES.md` 和当前 SQLite 计数为准。不要引用旧规则基线作为现状；
3. 改 Vue 页面时开后端 `8000` + Vite `5173`，浏览器走 `http://127.0.0.1:5173/`；`http://127.0.0.1:8000/` 只托管上次 `npm run build` 的 `dist/`；
4. 不要读取、打印、复制或提交 `.env`；旧 API 密钥曾在对话中暴露，应由用户轮换；
5. 默认不再调用外部 API。若用户再次明确授权，必须同时设置调用次数和 Token 硬上限；
6. 不覆盖 `run/data/application.db` 和冻结的 `run/data/full_api_20260827.db`；当前展示库是 `run/data/v0.2_local_20260828.db`；
7. 不覆盖官方 `dataset_build/blocks/`（仍为 Parser 2.0）和 v0.1 结果目录；新实验写新目录。
>>>>>>> Stashed changes

## 1. 项目目标

项目要实现一个可离线部署的招采标讯分析系统，覆盖三项赛题任务：

- 任务一：从公告HTML和附件中抽取产品/服务名称、品目、品牌/制造商/产品供应商、规格型号、单价、数量、总价，并保留Block证据。
- 任务二：抽取采购单位、代理机构、包件、中标供应商、投标参与方、报价、得分、排名和审查结果，完成五类业务分析及关系图。
- 任务三：用Vue + Python完成批量导入、任务状态、任务一检索/详情/导出、任务二场景、项目图谱和系统状态。最终比赛目标是无外网运行。

## 2. 当前技术栈和整体架构

| 层级 | 当前技术 |
|---|---|
| 运行环境 | Windows、Conda `Aproject`、Python 3.11 |
| 文档解析 | lxml、python-docx、openpyxl、xlrd、PyMuPDF、Pillow |
| OCR | RapidOCR + ONNX Runtime，不依赖PyTorch |
| 老版Office | 项目内LibreOffice 26.2.5 headless |
| 智能体 | LangGraph 1.x、OpenAI兼容Chat、Pydantic v2 |
| 搜索试验 | DDGS + Replay + 持久缓存 |
| 数据库 | SQLite WAL、索引、六张预计算关系表 |
| 后端/前端 | FastAPI、Uvicorn / Vue 3、TypeScript、Vite、ECharts |
| 导出/测试 | CSV、openpyxl XLSX / pytest、TestClient、vue-tsc |

```text
HTML + 附件ZIP
  → Parser 2.1多格式提取、安全递归解包、原生PDF水印过滤、OCR
  → 统一Block JSON
  → Selector 1.3本地筛选与请求分块
  → 任务一LangGraph Agent 2.1
       ├─ 强表规则快速通道
       └─ 弱表/正文：外部API或本地OpenAI兼容模型
  → Schema/证据/金额校验、最多一次修复
  → 公告级来源过滤、去重与冲突处理
  → 任务一JSON

同一批Blocks
  → 任务二候选抽取
  → Relation Agent 1.4
       ├─ 常规模型抽取与一次修复
       └─ 超大强结构投标表本地通道
  → Pydantic与Block坐标校验
  → 任务二JSON

任务一 + 任务二结果 → SQLite → FastAPI → Vue检索/导出/五场景/项目图
```

Parser和Selector完全本地运行。最终本地部署只需把Agent后端从外部API切换到本地OpenAI兼容服务，数据契约不变。

## 3. 已经完成的功能

### 3.1 数据、Parser和Selector

- 291篇结果公告HTML，243篇有附件ZIP；
- Parser 2.0完成291/291篇：1,503个文档、274,597个Blocks；文档状态ok=1,471、partial=23、error=2、unsupported=7；最新代码已为2.1.0，正式目录尚未覆盖；
- 支持HTML、DOC/DOCX、XLS/XLSX、PDF、图片、TXT、JSON；ZIP/RAR最多三层安全递归解包；
- 已实现分卷RAR归组、RapidOCR、LibreOffice老格式转换、PDF表格重叠抑制、稳定内容寻址Block ID；
- 正式产物Parser 2.0.0、Schema 1.1、配置摘要`61bfe1df950c6cd2a13ad44d5844382f9349151bfaa03f27fdab07147c17bcbc`；最新代码Parser 2.1.0默认摘要`f1a4cb0443b02b38af035bf43f26f97cc264315a2aba24d206a8525f5d0a5544`；
- Parser 2.1.0仅在页级确认完整标识型水印且表格字符完整复原同一序列时过滤；真实`20241217_23892691` PDF回归移除16张表共800个字符，并保留`JSGS01`、`Q235`、`DS-2CD3T26WDA4-L`；
- `dataset_build/model_inputs/`已是Selector 1.3全量产物：3,716个来源Blocks、1,411个请求、98.65%压缩率、完整性错误0；
- 20篇金标的22个来源Block和127个唯一证据行召回均为100%。

### 3.2 金标和银标

- 人工金标：20篇、128条，覆盖HTML/XLSX/DOCX/PDF，强证据和金额校验通过；
- 金标仍是单人标注种子，没有第二人独立复核；
- API银标：116篇、2,315条，位于`dataset_build/silver/`，不等于人工真值。

### 3.3 任务一全量API闭环

当前权威结果：`run/full_api_20260827/agent2_curated/`。

- Agent 2.1.0；291篇、1,411/1,411请求成功；最终3,552条实体；
- 历史API用量708次、1,227,898 Token；
- 超长OCR请求按7页恢复115条明细；
- 采购需求、空白报价模板、项目总价摘要已在模型前或公告合并阶段过滤；
- 20篇金标证据召回100%，严格全字段一致112/128=87.5%，字段一致率94.53%–100%；
- 3,552个主证据坐标和4,085个补充引用全部有效。

这些指标来自20篇单人金标，不能写成291篇全量人工准确率。

### 3.4 任务二全量API闭环

当前权威结果：`run/full_api_20260827/relation_api/`。

- Relation Agent 1.4.0；291/291篇成功；
- 303个包件、563条竞标关系、1,009个机构；
- 最终有效结果382次调用、3,705,708 Token；含失败重试的历史用量400次、4,004,392 Token；
- 198篇直接模型成功、92篇一次修复、1篇超大强表本地通道；
- 563条关系都有证据，1,234个引用全部有效；
- 291篇都有竞标关系，287篇有明确中标/成交关系；
- 模型别名字段、文本行号、越界表格行和空白模板均已确定性处理。

任务二没有人工金标，Schema和证据通过率不是关系准确率。

### 3.5 任务三全量平台闭环

隔离数据库：`run/data/full_api_20260827.db`。

<<<<<<< Updated upstream
- 任务一291篇/3,552实体，任务二291项目/303包件/563竞标关系，导入失败0；
- CSV与XLSX均完整导出3,552行；
- 五类业务场景的六个接口和项目关系图在全量库上返回非空结果；
- 单次搜索约8ms、关系查询约2.5–4.2ms、全量XLSX约0.60s；
- 58项pytest、Python编译检查和Vue生产构建通过。
=======
- 上传不再只暂存：`src/api/pipeline.py` 把 HTML/ZIP 跑完 Parser → Selector/SlotPacker → Agent → SQLite；JSON/JSONL 可直接入库；
- SSE 在 `completed`/`failed` 结束；前端 `ImportView.vue` 用 EventSource 跟踪；
- 默认 `APP_PIPELINE_BACKEND=local`；测试可用 `--pipeline-backend rules`；
- 重复 `package_no` 入库时后缀 `#2`；同一包件重复机构跳过（`src/relation/store.py`）；
- 最近一次完整 pytest：**85 项通过**（含 `tests/integration/test_pipeline.py`）；`compileall` 和 Vue 生产构建通过。
- 2026-09-03 前端展示优化（业务流程与主视觉不变）：导入页按任务一/二切换简介与流程；检索表固定列宽/行高/滚动区；图谱改为分层静力布局，节点可拖拽且无弹力回拉。
>>>>>>> Stashed changes

这些是单次本机验收值，不是多轮并发P95。

### 3.6 联网时序核验

- LangGraph ToolNode、搜索预算、真实URL回指、Replay和缓存已实现；
- “新华三”小样本跑通；
- 全量没有执行；DDGS不是权威工商或商标数据源；
- 核验结果只附加到原文实体，不覆盖`brand_supplier`。

## 4. 当前正在进行的任务

<<<<<<< Updated upstream
- 关系图已完成节点形状、连接度尺寸、长标签提示、悬停边标签和密集投标方聚合/展开改版；“默认包”按用户要求保留。
- PDF水印过滤代码和真实单文件回归已完成。Parser 2.1.0 隔离全量已跑完：`run/parser_2_1_20260828/`，配置摘要 `f1a4cb0443b02b38af035bf43f26f97cc264315a2aba24d206a8525f5d0a5544`，291/291 成功。对比报告 `run/parser_2_1_20260828/compare_report.md`。水印只影响非金标 `20241217_23892691`（16表/800字符）。20篇金标 Block 无变化。正式 `dataset_build/blocks/` 仍为 Parser 2.0.0，尚未覆盖。
- 下一步可只对 `20241217_23892691` 在隔离目录重跑 Selector；金标本地模型回归不必等 Parser 覆盖。
=======
平台页面展示与交互优化已完成（2026-09-03）。下一环节回到**抽取效果**，不是再改版式或再接通流水线。优先：
>>>>>>> Stashed changes

没有外部API批处理仍在运行。项目处于“全量外部API参考结果完成，本地LM Studio非thinking 4B已小样本接通，Parser 2.1隔离全量已对比，等待扩大回归与产品化补齐”阶段：

1. 本地LM Studio已接入：`http://127.0.0.1:1234`，当前模型 `qwen/qwen3-4b-2507`（非 thinking；thinking 版对照目录仍保留）。2026-08-28 对同一金标请求 `20260813_27128600:req_001` 重跑：约 25 秒、153 个输出 Token、1/1 成功未修复；thinking 对照为约 7.5 分钟、2940 Token。字段结果相同，仍把表格「品目号」写成 `category_code=1`。新结果 `run/local_lmstudio_20260828/gold1_instruct_probe/`。按此速度，20篇金标回归已可安排，仍不要直接跑 291 篇；
2. 准备用20篇金标对本地模型做同请求、同Schema回归；速度允许后再扩大；
3. 需要建立任务二人工关系金标；
4. 需要把上传暂存任务接入Parser→Selector→Agent→数据库。

## 5. 还未完成的任务

- 本地LM Studio `qwen/qwen3-4b-2507` 完成同口径 1 条金标对照；20篇金标与291篇全量回归未做；
- 4B 仍会把 Selector 映射的「品目号」写入 `category_code`，需要提示词/校验或更大模型才能当正式离线后端；
- 任务二人工金标、字段级P/R/F1和五场景人工断言；
- 金标双人独立复核和一致性统计；
- 上传后自动解析、筛选、抽取、入库和失败重试；
- 权威工商/商标/企业历史数据接口；
- 官方比赛数据薄适配器；
- 多轮并发P50/P95、模型吞吐和长时间稳定性测试；
- 一键离线部署、演示流程、PPT、视频和最终提交包。

## 6. 关键设计决策及原因

| 决策 | 原因 |
|---|---|
| 原始文件先统一为Block | 屏蔽格式差异，并保留表格、页码、文件路径和行级证据 |
| Block ID使用来源+内容哈希 | 避免解析顺序变化导致金标坐标漂移 |
| Parser/Selector不调用模型 | 降低成本，保证离线、可重复和易审计 |
| Agent使用LangGraph受控状态机 | 明确规则/模型路由、工具权限、校验、修复、断点和预算 |
| 强表使用受限本地通道 | 对明确列映射的结果表更快、更稳定，不浪费模型调用 |
| 弱表和正文交给模型 | 多实体位置和语义复杂，纯规则不足以稳定覆盖 |
| 来源策略区分结果附件与采购模板 | 防止采购需求、空白报价表、评分办法变成实际结果 |
| 证据回指是硬约束 | 防止模型伪造Block或行号，便于人工复核 |
| 超大投标表不让模型复述 | 105家投标人会超过完成Token上限，本地结构提取能完整保存 |
| SQLite加六张预计算表 | 免部署、可离线、查询快，适合比赛现场 |
| 相似主体只进审核队列 | 避免“华三/新华三”等差异被模糊匹配误合并 |
| API必须显式授权和硬预算 | 防止误调用和余额失控 |
| 外部核验不覆盖原文字段 | 搜索证据可能噪声、过时或未来污染 |

## 7. 曾尝试但放弃或降级的方案

1. Parser v1顺序Block ID：会导致金标漂移，已由稳定哈希替代；
2. 分卷RAR逐卷解析：造成分卷报错，已改为归组后只从首卷解压；
3. PDF段落与表格同时保留：会内容重叠，已加入表格区域段落抑制；
4. 每个筛选请求直接调用API：保留作银标工具，正式执行器改为受控Agent；
5. 纯规则处理所有实体：正文和弱表语义不足，现只用于强表和安全判空；
6. 把强表置信度当模型概率：当前置信度只是固定质量档位；
7. 让模型复述105家投标人：两次输出截断，已改为超大强表本地通道；
8. 自动模糊合并相似公司名：误合并风险过高，改成人工审核队列；
9. DDGS充当工商权威源：只保留为工程小样本搜索提供方；
10. Neo4j/Kuzu、NER/UIE、向量检索作为前置：当前SQLite与受控Agent已覆盖核心功能；
11. 4篇Codex离线替代响应：完成早期闭环验证，但已被291篇真实API全量结果替代，只保留作Replay。

## 8. 当前已知Bug或风险

1. Parser仍有2个文档`error`、7个专业格式`unsupported`，扫描PDF有OCR页数上限；正式Block仍为2.0.0，尚未应用2.1.0水印过滤；
2. 本地GGUF尚未实测，外部API结果不能证明本地部署效果；
3. 20篇金标规模小、单人标注，可能存在遗漏和系统偏差；
4. 任务二没有人工金标，模型可能在结构合法时产生关系语义错误；
5. 4篇任务二结果无明确赢家，可能是源证据不完整或模型漏识别，需要抽检；
6. `brand_supplier`同时容纳品牌、制造商和产品供应商，类型仍可能混淆；
7. 全量企业/品牌联网核验未做，普通搜索不能替代权威登记；
8. 上传只暂存，不自动进入完整流水线；
9. ECharts图谱分包约509KB，Vite有大包警告，但当前构建正常；密集普通投标方已支持聚合与手动展开；
10. 当前目录无Git仓库，修改后依赖测试、隔离目录和报告审计；
11. API密钥曾在旧对话暴露，必须轮换；不得出现在回复、命令输出、文档或日志中；
12. 当前性能数字是单次本机TestClient结果，不代表并发P95。

## 9. 重要文件和目录

### 文档

| 路径 | 作用 |
|---|---|
| `PROJECT_GUIDE.md` | 当前总体业务、架构和实施顺序 |
| `HANDOFF.md` | 新会话交接入口 |
| `block转化流程.md` | 原始HTML/附件到Block的运行流程 |
| `docs/BLOCK_PARSER.md` | Parser技术契约 |
| `docs/MODEL_INPUT_SELECTOR.md` | Selector评分、切分和输出契约 |
| `docs/ENTITY_EXTRACTION_AGENT.md` | 任务一Agent与联网核验 |
| `docs/TASK2_RELATION_SYSTEM.md` | 任务二Schema、存储和五场景 |
| `docs/TASK3_PLATFORM.md` | FastAPI/Vue平台 |
| `run/full_api_20260827/FULL_PIPELINE_REPORT.md` | 本轮291篇全量验收权威说明 |

### 核心代码与入口

| 路径 | 作用 |
|---|---|
| `src/parsing/` | 多格式解析、OCR、安全解包与Block生成 |
| `src/extraction/block_selector.py` | 本地筛选和请求构建 |
| `src/agents/entity_extraction_agent.py` | 任务一LangGraph状态机 |
| `src/agents/source_policy.py` | 结果附件、采购模板和低价值来源策略 |
| `src/agents/validators.py`、`merger.py` | 任务一校验与公告级合并 |
| `src/agents/backends.py` | API/本地/Replay/Fake后端与预算 |
| `src/agents/verification/` | 时序联网核验子图 |
| `src/relation/agent.py` | Relation Agent 1.4、证据修正和超大表通道 |
| `src/relation/extractor.py`、`schema.py` | 任务二候选与数据契约 |
| `src/relation/store.py`、`queries.py` | SQLite关系库、预计算和查询 |
| `src/api/app.py`、`database.py` | FastAPI、证据回读、导出与任务一存储 |
<<<<<<< Updated upstream
| `frontend/src/` | Vue页面和ECharts组件 |
| `scripts/run_entity_agent.py` | 任务一规则/API/本地/Replay入口 |
| `scripts/recover_chunked_entity_request.py` | 超长任务一请求分块恢复 |
| `scripts/rebuild_entity_results.py` | 从断点重建任务一公告结果 |
| `scripts/run_relation_agent.py` | 任务二规则/API/本地/Replay入口 |
| `scripts/init_app_db.py` | 导入任务一、任务二目录到SQLite |
=======
| `src/api/jobs.py` | 上传文件名安全化 |
| `frontend/src/views/ImportView.vue` | 上传与 SSE；任务一/二简介和流程随切换更新 |
| `frontend/src/views/Task1View.vue` | 标的物检索：固定规格表、行点选详情 |
| `frontend/src/views/GraphView.vue` | 项目子图：分层静力布局、可拖拽、无弹力 |
| `frontend/src/components/RelationChart.vue` | ECharts 图；`layout: 'none'` |
| `frontend/src/style.css` | 主视觉（海军蓝侧栏、米色纸面、珊瑚色按钮） |
| `frontend/vite.config.ts` | 开发服务 `127.0.0.1:5173`，`/api` 代理到 `8000` |
| `scripts/run_server.py` | 单端口启动；`--pipeline-backend local\|rules` |
| `scripts/run_entity_agent.py` | 任务一规则/API/本地/Replay 入口 |
| `scripts/run_relation_agent.py` | 任务二规则/API/本地/Replay 入口 |
| `scripts/init_app_db.py` | 导入任务一、任务二目录到 SQLite |
>>>>>>> Stashed changes
| `scripts/verify_full_pipeline.py` | 全量坐标、API、导出、场景和耗时验收 |
| `scripts/summarize_agent_state.py` | 历史调用和Token统计 |

### 当前权威产物

| 路径 | 内容 |
|---|---|
| `dataset_build/blocks/notices/` | 291篇Parser 2.0 Blocks |
| `dataset_build/model_inputs/` | 291篇Selector 1.3、1,411请求 |
| `dataset_build/gold/` | 20篇128条人工金标种子 |
| `run/full_api_20260827/agent2_api/` | 任务一原始API结果和断点 |
| `run/full_api_20260827/agent2_curated/` | 任务一最终3,552实体 |
| `run/full_api_20260827/relation_api/` | 任务二最终291篇关系结果 |
| `run/full_api_20260827/platform_verification.json` | 坐标、接口、导出和耗时机器报告 |
| `run/full_api_20260827/exports/` | 3,552行CSV/XLSX |
| `run/data/full_api_20260827.db` | 当前全量隔离演示数据库 |

## 10. 下一步最推荐做的事情

<<<<<<< Updated upstream
1. 轮换密钥并冻结外部API结果：不要重复调用已成功的291篇；
2. 在隔离目录重跑Parser 2.1.0，比较受水印影响的公告并重跑对应Selector；不要覆盖2.0.0正式目录；
3. 本地模型20篇回归：使用与Parser版本一致的新请求和金标，对比同口径指标、失败率和速度；
4. 20篇通过后再50篇、291篇，必须断点续跑，不覆盖外部API参考目录；
5. 建立任务二人工金标，优先多包、联合体、长表、审查结果等复杂样本；
6. 接通上传流水线：Parser、Selector、两个Agent和隔离入库，补失败重试与阶段进度；
7. 接权威企业/商标历史数据源，普通网页搜索只作补充；
8. 官方数据到达后写薄适配器，再做并发性能、一键启动、演示和提交包。

本地模型第一次测试不要直接跑291篇，也不要使用外部API目录作为输出目录。
=======
1. 轮换密钥；不要重复调用已成功的 291 篇外部 API；
2. 前端展示优化已完成。改 Vue 用 Vite `5173` + 后端 `8000`，不要每次 `npm run build`；
3. 优化任务一：`category_code` 误填品目号、弱表/正文漏抽；用 20 篇金标做同口径回归后再扩样本；
4. 隔离补跑剩余空实体 / 失败篇（4B 或 9B 均可），输出写新目录，成功后再选择性入库；不要覆盖 `task1_full_291/` / `task2_full_291/` 里已成功 JSON；
5. 建立任务二人工关系金标，优先多包、联合体、长表、审查结果等复杂样本；
6. 金标双人复核；
7. 官方数据到达后写薄适配器；再做并发性能、一键启动、演示和提交包；
8. 若赛题最终要求自带 GGUF，再把 llama.cpp 落盘并做同口径回归；当前迭代不要把“LM Studio 能跑”写成“提交包已含模型”。
>>>>>>> Stashed changes

## 11. 新人接手时特别注意

1. 不读取、不打印`.env`，任何文档和命令都不得包含真实Key；
2. 不要重复全量API；已有291篇成功结果，只有用户再次明确授权且确有新实验时才调用；
3. 区分外部API参考结果和最终本地模型结果；
4. 不要把单人金标指标写成全量准确率；
5. 不要把任务二Schema/证据通过率写成关系准确率；
6. 不覆盖旧产物和正式库，新实验使用新目录和新SQLite文件；
7. 优先复用断点，任务一/二入口都支持输入摘要复用；
8. 修改后跑58项pytest、`compileall`和Vue构建；涉及结果时再跑`verify_full_pipeline.py`；
9. 任何合并、去重和归一化都必须保留真实Block与合法行号；
10. 相似公司名不自动合并，特别是华三/新华三及历史重组、收购、品牌与法人差异；
11. 当前无Git，修改前确认用户文件和旧结果，必要时使用隔离副本；
12. 若旧文档数字冲突，以全流程报告、manifest和机器报告为准。

## 常用迭代命令

工作目录一律先 `cd D:\all_contest\2026_8_15_proc-bid-ner`。Python 用 Conda 环境 `Aproject` 的解释器，避免 `conda run` 把子进程挂到错误目录。

### 前端迭代（改 Vue 时用这个，不要每次 `npm run build`）

两个进程都要开。Vite 把 `/api` 转到 8000。浏览器打开 **`http://127.0.0.1:5173/`**，不要只开 8000（那是上次构建的 `dist/`）。

终端 1，后端 API：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
```

终端 2，Vite 热更新：

```powershell
cd frontend
npm.cmd run dev
```

热更新丢了或代理 502 时：先确认 8000 仍在听，再重启 `npm run dev`。改 `vite.config.ts` 必须重启 Vite。

### 演示 / 生产形态（单端口托管 `frontend/dist`）

```powershell
cd frontend
npm.cmd run build
cd ..
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
```

<<<<<<< Updated upstream
重建隔离数据库：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/init_app_db.py `
=======
访问 `http://127.0.0.1:8000/`。

切回 v0.1 冻结库：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py `
>>>>>>> Stashed changes
  --db run/data/full_api_20260827.db `
  --import-task1 `
  --task1-dir run/full_api_20260827/agent2_curated/notices `
  --relation-dir run/full_api_20260827/relation_api/notices
```

全量工程验收：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/verify_full_pipeline.py `
  --db run/data/full_api_20260827.db `
  --task1-dir run/full_api_20260827/agent2_curated/notices `
  --relation-dir run/full_api_20260827/relation_api/notices `
  --blocks-dir dataset_build/blocks/notices `
  --export-dir run/full_api_20260827/exports `
  --output run/full_api_20260827/platform_verification.json
```

### 修改后检查

```powershell
D:\anaconda\envs\Aproject\python.exe -m pytest -q `
  --basetemp run/pytest_tmp_handoff `
  -o cache_dir=run/pytest_cache_handoff

D:\anaconda\envs\Aproject\python.exe -m compileall -q src scripts

cd frontend
npm.cmd run build
```

### 任务一 / 任务二隔离试跑（输出写新目录，不要覆盖全量 JSON）

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_entity_agent.py --backend rules

D:\anaconda\envs\Aproject\python.exe scripts/run_entity_agent.py `
  --backend local `
  --keep-covered-text `
  --max-model-calls 2 `
  --max-total-tokens 40000

D:\anaconda\envs\Aproject\python.exe scripts/run_relation_agent.py --backend rules --limit 20

D:\anaconda\envs\Aproject\python.exe scripts/run_relation_agent.py `
  --backend local `
  --max-model-calls 2 `
  --max-total-tokens 40000 `
  --ids 20260814_27138985 `
  --blocks-dir run/parser_2_1_20260828/notices `
  --output-dir run/scratch/relation_probe/notices
```

本地模型必须先在 LM Studio 加载 `qwen/qwen3-4b-2507`（`http://127.0.0.1:1234`）。不要 `--commit` 到正式展示库。
