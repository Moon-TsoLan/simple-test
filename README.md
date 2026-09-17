# 识别与关系建模

项目总体设计、技术栈、任务流程见 [PROJECT_GUIDE.md](./PROJECT_GUIDE.md)。新会话接手先读 [HANDOFF.md](./HANDOFF.md)，文档职责与阅读顺序见 [docs/README.md](./docs/README.md)。

> **模型路线**：赛题允许赛前调用 API。本项目采用 **“API 做银标打标与提示词迭代 + 本地离线小模型做最终评测系统”** 的双轨制。API 不进入最终系统调用链。

<<<<<<< Updated upstream
> **最新全量验收（2026-08-27）**：291篇已完成Parser 2.0、Selector 1.3、任务一Agent 2.1、任务二Relation Agent 1.4、隔离数据库和FastAPI/Vue全链路测试。任务一1,411/1,411请求成功并得到3,552条实体；任务二291/291篇成功并得到563条竞标关系；56项pytest和Vue生产构建通过。详见 [全流程报告](./run/full_api_20260827/FULL_PIPELINE_REPORT.md)。
=======
> **当前页面展示（2026-09-03）**：v0.2 库 + Parser 2.1。上传流水线已接通，运行时本地模型 `qwen/qwen3-4b-2507`。前端展示已优化（导入任务简介、检索表规格、图谱静力布局）。磁盘上的全量 JSON 仍是 9B 产物（任务一 3,184 实体，任务二 282/291）；当前 SQLite 在此基础上多了两篇 4B 上传样本（3,185 实体 / 283 项目）。质量说明见 [QUALITY_AND_DISPLAY.md](./run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md)，样本见 [PIPELINE_SAMPLES.md](./run/v0.2_local_20260828/PIPELINE_SAMPLES.md)。v0.1 API 冻结库不要覆盖。改页面请用 Vite `5173` + 后端 `8000`，命令见 [HANDOFF.md](./HANDOFF.md)。

> **v0.1 全量验收（2026-08-27，已冻结）**：Parser 2.0 + DeepSeek API。任务一 3,552 实体、任务二 291/291 篇、563 条竞标。详见 [全流程报告](./run/full_api_20260827/FULL_PIPELINE_REPORT.md)。
>>>>>>> Stashed changes

## 当前进度

- [x] 项目目录结构
- [x] 项目指导文档 `PROJECT_GUIDE.md`
- [x] 数据下载脚本 `scripts/crawl/download_ccgp.py`
- [x] 批量下载：291 篇公告 HTML、243 个附件 zip，全部扩展名均 ≥5（统计见 `dataset_build/manifests/data_report.md`）
- [x] 解析环境：项目内 LibreOffice 26.2.5、PyMuPDF、RapidOCR/ONNX 已安装并完成291篇标准解析
- [ ] 推理环境：llama.cpp / 本地 Qwen GGUF 尚未落盘和实测；RAR当前依赖系统可用解压器
- [x] 多格式附件统一解析器 `src/parsing/`（统一 blocks、递归安全解包、OCR/老格式降级审计）
- [x] 本地 Block 筛选与模型输入生成 `src/extraction/block_selector.py`（输出 `dataset_build/model_inputs/api_requests.jsonl`）
- [x] LangGraph 受控实体抽取智能体 `src/agents/`：规则/模型状态图、证据/金额校验、有限修复、跨请求合并、断点续跑，以及可选公司/品牌时序联网核验 ToolNode
- [x] API 银标：DeepSeek `deepseek-chat` 已完成 116 篇公告、2315 条银标（`dataset_build/silver/`；规则基线归档在 `dataset_build/silver_rules_v1/`）
- [x] 规则银标基线：`scripts/build_silver_labels.py`（已归档，保留为回退与对比基线）
- [x] 人工金标种子20篇、128条，均通过证据与金额强校验
- [ ] 金标双人独立复核、一致性统计及继续扩充
- [ ] 官方数据格式适配器 `scripts/adapt/official_adapter.py`
- [x] 任务一全量API验证：291篇、1,411请求全部完成，最终3,552条实体；20篇金标证据召回100%、严格全字段一致87.5%
- [x] 任务二全量API验证：291篇全部完成，303个包件、563条竞标关系、1,234个有效证据引用
- [x] 任务三全量隔离库验证：检索、证据回读、3,552行CSV/XLSX导出、五场景和项目子图全部通过
<<<<<<< Updated upstream
- [ ] 原始上传后自动触发Parser→Selector→任务一/二Agent→入库
=======
- [x] v0.2 本地 9B 全量并切换页面展示：任务一 3,184 实体，任务二 282/291 入库；见 `run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md`
- [x] 上传流水线：Parser → Selector/SlotPacker → Agent → 入库 → 页面；4B 已实测任务一 `20260723_26991563` 与任务二 `20260815_27141428`；当前库 3,185 实体 / 283 项目
- [x] 前端展示优化：导入页任务简介/流程切换，检索表固定规格，图谱分层静力布局（可拖拽、无弹力）
>>>>>>> Stashed changes

## 数据下载

```powershell
cd D:\all_contest\2026_8_15
python scripts/crawl/download_ccgp.py --mode all --max-pages 2 --max-notices 150
```

- 断点续抓，重复运行会自动跳过已完成公告。
- 原始数据：`dataset_build/crawl/html`、`dataset_build/crawl/attachments`
- 官方同构镜像：`dataset_build/mirror_task1/notices`、`dataset_build/mirror_task1/attachments`
- 元数据清单：`dataset_build/manifests/manifest.json`、`manifest.csv`

## API 银标路线

```text
本地多格式解析（blocks）
  → 本地相关 Block 筛选与 OpenAI 兼容请求分块
  → 规则预抽取候选
  → API 结构化抽取/校验（Qwen / DeepSeek，OpenAI 兼容）
  → 本地强校验（金额一致性、品牌≠中标供应商、证据非空）
  → 银标入库：dataset_build/silver/
```

- API 配置：`config/llm_config.yaml`（模板 `llm_config.yaml.example`），Key 只放环境变量。
- 费用与用量记录：`run/logs/llm_usage.jsonl`。
- 断点续跑：`run/state/silver_state.jsonl`。
- 最终评测系统仍使用本地离线 Qwen GGUF + llama.cpp。

## 实体抽取智能体

默认运行不调用模型、不产生费用：

```powershell
conda run -n Aproject python scripts/run_entity_agent.py --backend rules
conda run -n Aproject python scripts/evaluate_entity_agent.py
```

当前`dataset_build/model_inputs/`已是Selector 1.3全量产物：从274,597个Blocks筛到3,716个来源Blocks，生成1,411个请求，完整性错误为0。外部API全量结果位于`run/full_api_20260827/agent2_curated/`；最终本地部署时改用`--backend local`并先做20篇金标同口径回归。外部API仍必须同时设置显式授权、调用上限和Token上限。详见 [docs/ENTITY_EXTRACTION_AGENT.md](./docs/ENTITY_EXTRACTION_AGENT.md)。

## 任务二关系系统

默认只生成可审计候选，不调用模型，也不会把候选冒充确认关系写入数据库：

```powershell
conda run -n Aproject python scripts/run_relation_agent.py --backend rules --limit 20
```

本地模型服务就绪后，使用 `--backend local --commit` 只提交通过 Schema 与证据回指校验的结果。技术选型、数据模型和五场景口径见 [docs/TASK2_RELATION_SYSTEM.md](./docs/TASK2_RELATION_SYSTEM.md)。

当前外部API全量验证结果位于`run/full_api_20260827/relation_api/`，291/291篇成功。Relation Agent 1.4会归一化模型常见字段/行号错误，并在超大强结构投标表上使用本地通道，避免模型输出被截断。

## 本地可视化平台

改 Vue 页面时开两个进程，浏览器访问 `http://127.0.0.1:5173/`：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm.cmd run dev
```

演示用单端口托管构建产物，访问 `http://127.0.0.1:8000/`：

```powershell
cd frontend
npm install
npm run build
cd ..
conda run -n Aproject python scripts/init_app_db.py `
  --db run/data/full_api_20260827.db `
  --import-task1 `
  --task1-dir run/full_api_20260827/agent2_curated/notices `
  --relation-dir run/full_api_20260827/relation_api/notices
conda run -n Aproject python scripts/run_server.py
```

<<<<<<< Updated upstream
启动隔离全量库时设置`APP_DB_PATH=run/data/full_api_20260827.db`，访问 `http://127.0.0.1:8000/`。不要覆盖旧`run/data/application.db`。详见 [docs/TASK3_PLATFORM.md](./docs/TASK3_PLATFORM.md)。
=======
默认读取 v0.2 库 `run/data/v0.2_local_20260828.db` 和 Parser 2.1 Blocks。上传 HTML/ZIP 会走 Parser → Agent → 入库。不要覆盖 `run/data/application.db` 或冻结的 `run/data/full_api_20260827.db`。切回 v0.1 时加 `--db run/data/full_api_20260827.db --block-dir dataset_build/blocks/notices`。完整命令见 [HANDOFF.md](./HANDOFF.md)，页面说明见 [docs/TASK3_PLATFORM.md](./docs/TASK3_PLATFORM.md)。
>>>>>>> Stashed changes

## 本地模型替代小样本闭环

本地模型暂不可用期间，已由 Codex 对4篇公告生成离线模型替代响应，并通过与真实模型相同的校验、合并、入库和查询链完成闭环：26个文档、3,755个Blocks、34个请求、8条任务一实体、4个任务二项目，五个关系场景均得到非空测试结果，外部API调用0。产物与复现方法见 [试运行说明](./dataset_build/pilot/model_substitute_20260826/README.md)。

## 目录

| 目录 | 用途 |
|---|---|
| `config/` | API 模型配置（`llm_config.yaml`，Key 走环境变量） |
| `docs/` | 设计、报告、交付物 |
| `dataset_build/` | 自建数据集、金标、银标、镜像 |
| `models/` | LLM / NER / OCR / embedding 模型 |
| `src/` | 后端核心代码，含 `agents/` 受控抽取智能体与 `services/` API 打标模块 |
| `frontend/` | Vue3 前端 |
| `scripts/` | 抓取、适配、评估、部署脚本 |
| `tests/` | 单元、集成、评估用例 |
| `results/` | 任务输出与评测结果 |
| `run/` | 日志、模型缓存、打标状态、临时文件 |
| `submission/` | 最终提交包 |
