# Codex项目交接文档

> 交接日期：2026-09-17
> 工作区：`D:\all_contest\2026_8_15_proc-bid-ner`（Git 仓库；提交由用户亲自操作）
> Python：Conda `Aproject`，Python 3.11
> 当前页面：v0.2 库 `run/data/v0.2_local_20260828.db` + Parser 2.1 Blocks `run/parser_2_1_20260828/notices`
> 上传流水线：已接通（`src/api/pipeline.py`）；**2026-09-17 方向调整：后端切换为外部 API 并在此基础上优化；数据集将切换为官方约 1000 条；测试以处理流程正常为准**
> 本地模型（备份路线）：LM Studio `qwen/qwen3-4b-2507`（运行时）/ `qwen3.5-9b`（批处理）@ `http://127.0.0.1:1234`
> 前端：改页面请走 Vite `5173` + 后端 `8000`
> 本轮清理（2026-09-17）：删除 `dataset_build/crawl/`、`third_party/installers/`、`run/tmp/`、各 pytest 缓存与冒烟目录、空脚手架目录（models/results/submission/docs子目录等），约 1.9GB；4 个核心文档已消除冲突标记重写。

## 接手后先做什么

1. 先读本文，再读 `PROJECT_GUIDE.md` 和当前模块的 `docs/*.md`；
2. 页面默认读 v0.2 库。v0.1 API 全量事实以 `run/full_api_20260827/FULL_PIPELINE_REPORT.md` 为准；v0.2 以 `run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md` 为准；不要引用旧规则基线作为现状；
3. 不要读取、打印、复制或提交 `.env`；旧 API 密钥曾在对话中暴露，应由用户轮换；
4. 默认不再调用外部 API。若用户再次明确授权，必须同时设置调用次数和 Token 硬上限；
5. 不覆盖 `run/data/application.db`、冻结的 `run/data/full_api_20260827.db` 和 `run/data/v0.2_local_20260828.db`；新实验写新目录和新 SQLite 文件；
6. 官方数据到达后先写薄适配器（映射为 mirror 同构输入），不改核心流水线。

## 1. 项目目标

覆盖三项赛题任务（2026-09版赛题五）：

- 任务一：从公告HTML和附件抽取7字段（产品服务名称、品目、品牌（产品供应商）、规格型号、单价、数量、总价），保留Block证据；
- 任务二：抽取采购单位、代理机构、包件、中标供应商、投标参与方、报价、得分、排名和审查结果，完成五类业务分析及关系图；
- 任务三：Vue + Python平台，批量导入、任务状态、任务一检索/详情/导出、任务二场景、项目图谱和系统状态。

## 2. 当前技术栈和整体架构

| 层级 | 当前技术 |
|---|---|
| 运行环境 | Windows、Conda `Aproject`、Python 3.11 |
| 文档解析 | lxml、python-docx、openpyxl、xlrd、PyMuPDF、Pillow、RapidOCR/ONNX、项目内LibreOffice 26.2.5 |
| 智能体 | LangGraph 1.x、OpenAI兼容Chat、Pydantic v2 |
| 数据库 | SQLite WAL、索引、六张预计算关系表 |
| 后端/前端 | FastAPI、Uvicorn / Vue 3、TypeScript、Vite、ECharts |
| 导出/测试 | CSV、openpyxl XLSX / pytest、TestClient、vue-tsc |

```text
HTML + 附件ZIP
  → Parser 2.1多格式提取、安全递归解包、原生PDF水印过滤、OCR
  → 统一Block JSON → Selector 1.3本地筛选与请求分块
  → 任务一LangGraph Agent 2.1（强表规则快速通道 / 弱表正文走模型）
  → Schema/证据/金额校验、最多一次修复 → 公告级合并 → 任务一JSON
同一批Blocks → 任务二候选 → Relation Agent 1.5 + SlotPacker → 校验 → 任务二JSON
任务一+任务二 → SQLite → FastAPI → Vue检索/导出/五场景/项目图
上传流水线（src/api/pipeline.py）：HTML/ZIP → Parser → Selector/SlotPacker → Agent → 入库，SSE进度
```

## 3. 已经完成的功能

### 3.1 数据、Parser和Selector

- 291篇结果公告HTML、243篇附件ZIP（镜像 `dataset_build/mirror_task1|task2/`；原始crawl已清理，可用 `scripts/crawl/` 重新抓取）；
- Parser 2.1.0：HTML、DOC/DOCX、XLS/XLSX、PDF、图片、TXT、JSON，ZIP/RAR最多三层安全递归解包；分卷RAR归组、RapidOCR、LibreOffice老格式转换、PDF表格重叠抑制、页级强水印过滤、稳定内容寻址Block ID；
- Selector 1.3全量产物：3,716来源Blocks、1,411请求、98.65%压缩率；20篇金标证据召回100%。

### 3.2 金标和银标

- 人工金标20篇128条（单人标注种子，未双人复核）；API银标116篇2,315条（`dataset_build/silver/`）；规则基线归档 `dataset_build/silver_rules_v1/`（技术路线对比素材）。

### 3.3 任务一闭环

- v0.1（冻结，`run/full_api_20260827/agent2_curated/`）：Agent 2.1.0、291篇1,411/1,411请求成功、3,552实体；历史API 708次/1,227,898 Token；20篇金标严格全字段一致87.5%；
- v0.2（本地9B，`run/v0.2_local_20260828/task1_full_291/`）：3,184实体、262篇有结果（29篇本地请求失败为空）；金标严格一致81.25%。

### 3.4 任务二闭环

- v0.1（冻结，`run/full_api_20260827/relation_api/`）：291/291篇、303包件、563竞标关系、证据引用全部有效；
- v0.2（Relation Agent 1.5.2 + SlotPacker 1.0）：282/291成功、508竞标；4篇成功JSON曾因重复package_no无法入库，入库时改为`包件号#2`。

### 3.5 任务三平台

- 上传不再只暂存：`src/api/pipeline.py` 全自动 Parser → Selector/SlotPacker → Agent → SQLite；SSE 在 `completed`/`failed` 结束；前端 `ImportView.vue` 用 EventSource 跟踪；
- 重复 `package_no` 入库时后缀 `#2`；同一包件重复机构跳过（`src/relation/store.py`）；
- 任务一检索/详情/证据回读/CSV·XLSX导出；任务二五场景+图谱（分层静力布局、可拖拽）；系统状态页；
- 最近一次完整 pytest：**59项通过**（compileall 和 Vue 生产构建通过）。注：旧交接文档曾写"85项"，经查证 `tests/integration/test_pipeline.py` 从未进入本仓库，当前仓库实际收集 59 项；
- 2026-09-03 前端展示优化：导入页任务简介/流程切换、检索表固定规格、图谱静力布局。

### 3.6 联网时序核验

- LangGraph ToolNode、搜索预算、真实URL回指、Replay和缓存已实现；"新华三"小样本跑通；全量未执行；核验结果只附加到原文实体。

## 4. 当前方向与进行中的任务

**2026-09-17 决策：更换数据集 + 流水线切外部 API + 在现有基础上优化。测试仅需验证处理流程正常。**

1. 官方数据薄适配器（映射为 mirror 同构输入）；
2. 流水线后端切外部 API：`--backend api` / `APP_PIPELINE_BACKEND` 代码已支持，需把默认值与配置切到 API，加并发与批量，验证1000条级吞吐；
3. 回归验证处理流程（pytest 59项 + 上传链路），顺手修复 `category_code` 品目号 bug（4B会把Selector映射的「品目号」写进 `category_code`）；
4. 按官方公式（准确率×0.4+精确率×0.3+召回率×0.3）建立评测脚本；任务二人工关系金标；
5. 最新赛题差距与行动优先级见 `docs/GAP_ANALYSIS_最新赛题对照_20260917.md`。

## 5. 关键设计决策及原因

| 决策 | 原因 |
|---|---|
| 原始文件先统一为Block | 屏蔽格式差异，保留表格、页码、文件路径和行级证据 |
| Block ID使用来源+内容哈希 | 避免解析顺序变化导致金标坐标漂移 |
| Parser/Selector不调用模型 | 降低成本，保证离线、可重复和易审计 |
| Agent使用LangGraph受控状态机 | 明确规则/模型路由、工具权限、校验、修复、断点和预算 |
| 强表使用受限本地通道；弱表和正文交给模型 | 明确列映射的表更快更稳；正文语义复杂必须模型 |
| 来源策略区分结果附件与采购模板 | 防止采购需求、空白报价表、评分办法变成实际结果 |
| 证据回指是硬约束 | 防止模型伪造Block或行号，便于人工复核 |
| 超大投标表不让模型复述 | 105家投标人会超完成Token上限，本地结构提取完整保存 |
| SQLite加六张预计算表 | 免部署、查询快；Neo4j/Kuzu保留为可选投影层 |
| 相似主体只进审核队列 | 避免"华三/新华三"等差异被模糊匹配误合并 |
| API必须显式授权和硬预算 | 防止误调用和余额失控 |

曾尝试但放弃/降级：Parser v1顺序ID、分卷RAR逐卷解析、PDF段落表格同时保留、每请求直调API、纯规则全量、强表置信度当概率、模型复述105家投标人、自动模糊合并公司名、DDGS当工商权威源、Neo4j前置。

## 6. 当前已知风险

1. 官方适配器与1000条吞吐未验证（外部API切换是前提）；
2. 任务二无人工金标；五场景结果与官方基准比对口径未知；
3. `category_code` 误填品目号；
4. 20篇金标单人标注；金标双人复核未做；
5. 查询效率未按"含前端渲染"官方口径实测；无并发P95；
6. 提交物（PPT/双视频/设计文档/过程性文档）未启动，决赛权重翻倍；
7. ECharts图谱分包约508KB触发Vite体积警告（不影响功能）；
8. 少量历史目录被ACL锁定无法删除（`.pytest_cache`、`run/pytest_tmp_20260827_*`等空壳，均已gitignore，可用管理员终端手动删除）；
9. API密钥曾在旧对话暴露，必须轮换。

## 7. 重要文件和目录

| 路径 | 作用 |
|---|---|
| `src/parsing/` | 多格式解析、OCR、安全解包与Block生成 |
| `src/extraction/block_selector.py` | 本地筛选和请求构建 |
| `src/agents/entity_extraction_agent.py` | 任务一LangGraph状态机 |
| `src/agents/validators.py`、`merger.py` | 任务一校验与公告级合并 |
| `src/agents/backends.py` | API/本地/Replay/Fake后端与预算 |
| `src/relation/agent.py`、`store.py`、`queries.py` | 任务二Agent、SQLite关系库与查询 |
| `src/api/app.py`、`pipeline.py`、`jobs.py` | FastAPI、上传流水线、任务管理 |
| `frontend/src/views/` | ImportView / Task1View / GraphView 等 |
| `scripts/run_entity_agent.py`、`run_relation_agent.py` | 任务一/二入口（rules/api/local/replay） |
| `scripts/run_server.py` | 平台启动；`--pipeline-backend local\|rules` |
| `scripts/init_app_db.py` | 导入任务一、二目录到SQLite |
| `scripts/verify_full_pipeline.py` | 全量坐标、导出、场景和耗时验收 |
| `run/full_api_20260827/` | v0.1冻结权威产物（勿覆盖） |
| `run/v0.2_local_20260828/` | v0.2本地权威产物与质量报告 |
| `run/parser_2_1_20260828/` | Parser 2.1 Blocks（v0.2展示与上传使用） |
| `dataset_build/` | mirror镜像、blocks(2.0)、model_inputs、gold、silver、silver_rules_v1、agent_results、pilot |

## 8. 常用迭代命令

工作目录一律先 `cd D:\all_contest\2026_8_15_proc-bid-ner`。Python 用 Conda `Aproject` 解释器。

### 前端迭代（改 Vue 时用，不要每次 npm run build）

```powershell
# 终端1
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
# 终端2
cd frontend ; npm.cmd run dev
# 浏览器打开 http://127.0.0.1:5173/
```

热更新丢了或代理 502：先确认 8000 在听，再重启 `npm run dev`。改 `vite.config.ts` 必须重启 Vite。

### 演示 / 生产形态

```powershell
cd frontend ; npm.cmd run build ; cd ..
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
# 访问 http://127.0.0.1:8000/ ；切回 v0.1：--db run/data/full_api_20260827.db --block-dir dataset_build/blocks/notices
```

### 修改后检查

```powershell
D:\anaconda\envs\Aproject\python.exe -m pytest -q --basetemp run/pytest_tmp -o cache_dir=run/pytest_cache
D:\anaconda\envs\Aproject\python.exe -m compileall -q src scripts
cd frontend ; npm.cmd run build
```

### 任务一 / 任务二隔离试跑（输出写新目录，不要覆盖全量 JSON）

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_entity_agent.py --backend rules
D:\anaconda\envs\Aproject\python.exe scripts/run_relation_agent.py --backend rules --limit 20
# 本地模型试跑前先在 LM Studio 加载模型；不要 --commit 到正式展示库
```

## 9. 新人接手特别注意

1. 不读取、不打印 `.env`，任何文档和命令不得包含真实Key；
2. 不要重复全量API；只有用户明确授权且确有新实验时才调用；
3. 区分外部API结果和本地模型结果；不要把单人金标指标写成全量准确率；
4. 不要把任务二Schema/证据通过率写成关系准确率；
5. 不覆盖旧产物和正式库；新实验用新目录和新SQLite文件；
6. 优先复用断点；修改后跑59项pytest、compileall和Vue构建；
7. 任何合并、去重和归一化必须保留真实Block与合法行号；相似公司名不自动合并；
8. 若文档数字冲突，以机器可读manifest/report为准（优先级见 `docs/README.md`）。
