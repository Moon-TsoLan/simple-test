# 项目文档索引与事实源规则

<<<<<<< Updated upstream
本文用于解决项目中“总体规划、阶段记录和模块说明混在一起”导致的版本冲突。自2026-08-27全量验收后，文档按下面的职责维护。
=======
本文用于解决项目中“总体规划、阶段记录和模块说明混在一起”导致的版本冲突。自 2026-09-03 起，文档按下面的职责维护。
>>>>>>> Stashed changes

## 阅读顺序

1. 新会话接手：先读根目录`HANDOFF.md`。
2. 了解目标、当前架构和总进度：读根目录`PROJECT_GUIDE.md`。
3. 实际运行或修改某一模块：读对应模块文档和代码。
4. 核对数量、版本和测试结果：以机器可读manifest/report为准，不以历史说明中的数字为准。

## 文档职责

| 文档 | 唯一职责 |
|---|---|
| `README.md` | 项目入口、最短启动路径和当前状态摘要 |
<<<<<<< Updated upstream
| `HANDOFF.md` | 跨Codex会话交接：历史决策、风险、当前阻塞和下一步 |
=======
| `HANDOFF.md` | 跨会话交接：历史决策、风险、当前阻塞、下一步和常用迭代命令 |
>>>>>>> Stashed changes
| `PROJECT_GUIDE.md` | 当前有效的总体设计、架构、任务状态和实施顺序 |
| `docs/BLOCK_PARSER.md` | HTML与附件统一Block解析器的技术契约 |
| `block转化流程.md` | Block转换的中文运行手册、全量结果和故障处理 |
| `docs/MODEL_INPUT_SELECTOR.md` | 本地Block筛选及模型请求生成 |
| `docs/ENTITY_EXTRACTION_AGENT.md` | 任务一LangGraph抽取与联网时序核验 |
| `docs/TASK2_RELATION_SYSTEM.md` | 任务二关系抽取、存储与五场景 |
| `docs/TASK3_PLATFORM.md` | 任务三FastAPI、Vue与SQLite平台 |
| `run/full_api_20260827/FULL_PIPELINE_REPORT.md` | 291篇外部API全流程验收事实源 |
| `scripts/crawl/README.md` | 自建数据抓取和镜像同步 |

数据目录内的`README.md`只解释该批产物，不承担总体设计职责。

## 事实源优先级

当文档与产物冲突时，按以下顺序判断：

1. 当前代码中的版本常量和CLI参数；
2. 对应输出目录中的JSON manifest/report；
3. 模块文档；
4. `PROJECT_GUIDE.md`状态摘要；
5. 历史试运行报告。

当前必须特别区分：

<<<<<<< Updated upstream
- 解析器代码和全量产物都是Parser `2.0.0`；
- 筛选器代码和`dataset_build/model_inputs/`全量产物均为Selector `1.3.0`，共1,411请求；
- 当前任务一权威结果是`run/full_api_20260827/agent2_curated/`，Agent `2.1.0`、3,552实体；旧`dataset_build/agent_results/`只作规则基线；
- 当前任务二权威结果是`run/full_api_20260827/relation_api/`，Relation Agent `1.4.0`、291篇全部成功；
- 正式金标是20篇128条，仍是单人标注种子；
- 当前全量隔离库为`run/data/full_api_20260827.db`；旧`run/data/application.db`不得视作或覆盖为本轮结果。
=======
- 解析器代码为 Parser `2.1.0`；官方 `dataset_build/blocks/` 仍为 Parser `2.0.0`（274,597 Blocks）；v0.2 展示与上传用 `run/parser_2_1_20260828/notices`（274,586 Blocks）；
- 筛选器代码为 Selector `1.3.1`；`dataset_build/model_inputs/` 全量产物仍为 Selector `1.3.0`，共 1,411 请求；
- v0.1 任务一权威结果是 `run/full_api_20260827/agent2_curated/`，Agent `2.1.0`、3,552 实体；
- v0.2 任务一 9B JSON 是 `run/v0.2_local_20260828/task1_full_291/`、3,184 实体、262 篇有结果；当前库因 4B 上传多 1 条，为 **3,185 / 263 篇**；
- v0.1 任务二权威结果是 `run/full_api_20260827/relation_api/`，Relation Agent `1.4.0`、291 篇全部成功；
- v0.2 任务二 9B JSON 是 Relation Agent `1.5.2` + SlotPacker `1.0.0`，282/291 成功；当前库因 4B 上传多 1 个项目，为 **283 / 289 包件 / 509 竞标**；
- 正式金标是 20 篇 128 条，仍是单人标注种子；
- 当前页面展示库为 `run/data/v0.2_local_20260828.db`；v0.1 冻结库为 `run/data/full_api_20260827.db`；旧 `run/data/application.db` 不得覆盖；
- 上传流水线已接通（`src/api/pipeline.py`），默认本地模型 `qwen/qwen3-4b-2507` @ `127.0.0.1:1234`；
- 前端展示优化已落地：导入页任务简介/流程、检索表固定规格、图谱分层静力布局；改页面走 Vite `5173` + 后端 `8000`；
- 最近一次完整 pytest 为 85 项通过。
>>>>>>> Stashed changes

## 历史材料处理原则

早期Parser v1、25篇Parser v2试跑、Codex模型替代闭环等记录仍有诊断价值，但不再作为“当前状态”。历史结论应保存在对应报告或pilot目录，不应重新复制进总体指导书。需要引用时必须同时写明版本、样本范围和限制。
