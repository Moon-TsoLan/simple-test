# 项目文档索引与事实源规则

本文用于解决项目中“总体规划、阶段记录和模块说明混在一起”导致的版本冲突。自2026-08-27全量验收后，文档按下面的职责维护。

## 阅读顺序

1. 新会话接手：先读根目录`HANDOFF.md`。
2. 了解目标、当前架构和总进度：读根目录`PROJECT_GUIDE.md`。
3. 实际运行或修改某一模块：读对应模块文档和代码。
4. 核对数量、版本和测试结果：以机器可读manifest/report为准，不以历史说明中的数字为准。

## 文档职责

| 文档 | 唯一职责 |
|---|---|
| `README.md` | 项目入口、最短启动路径和当前状态摘要 |
| `HANDOFF.md` | 跨Codex会话交接：历史决策、风险、当前阻塞和下一步 |
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

- 解析器代码和全量产物都是Parser `2.0.0`；
- 筛选器代码和`dataset_build/model_inputs/`全量产物均为Selector `1.3.0`，共1,411请求；
- 当前任务一权威结果是`run/full_api_20260827/agent2_curated/`，Agent `2.1.0`、3,552实体；旧`dataset_build/agent_results/`只作规则基线；
- 当前任务二权威结果是`run/full_api_20260827/relation_api/`，Relation Agent `1.4.0`、291篇全部成功；
- 正式金标是20篇128条，仍是单人标注种子；
- 当前全量隔离库为`run/data/full_api_20260827.db`；旧`run/data/application.db`不得视作或覆盖为本轮结果。

## 历史材料处理原则

早期Parser v1、25篇Parser v2试跑、Codex模型替代闭环等记录仍有诊断价值，但不再作为“当前状态”。历史结论应保存在对应报告或pilot目录，不应重新复制进总体指导书。需要引用时必须同时写明版本、样本范围和限制。
