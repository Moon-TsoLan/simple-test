# 识别与关系建模

面向招采标讯的实体挖掘与关系建模系统（"中国电子杯"ICT大赛赛题五）。总体设计见 [PROJECT_GUIDE.md](./PROJECT_GUIDE.md)，新会话接手先读 [HANDOFF.md](./HANDOFF.md)，文档职责见 [docs/README.md](./docs/README.md)。

> **模型路线（2026-09-17 更新）**：按最新赛题，评测在命题方云平台进行，可使用赛事组提供的标准模型资源。策略调整为：**处理流水线切换为外部 API（OpenAI 兼容）并在此基础上优化，本地 Qwen 小模型保留为离线备份**。所有外部调用需显式授权并设置调用次数与 Token 硬上限，密钥只从环境变量读取。

> **当前状态（2026-09-17）**
> - 上传流水线（Parser → Selector/SlotPacker → Agent → 入库，SSE 进度）已接通；59 项 pytest 通过；
> - **数据集将切换**：官方约 1000 条数据发布后替换自建 291 篇（自建集降级为开发回归集），需编写官方数据薄适配器；测试以"处理流程正常"为准，不再追求自建集上的质量指标；
> - 最新赛题差距分析：[docs/GAP_ANALYSIS_最新赛题对照_20260917.md](./docs/GAP_ANALYSIS_最新赛题对照_20260917.md)；
> - 2026-09-17 已清理冗余目录与过时文档约 1.9GB，四个核心文档已消除 git 冲突标记并统一为最新状态。

## 数据与结果版本

| 版本 | 内容 | 位置 |
|---|---|---|
| v0.1（冻结） | Parser 2.0 + DeepSeek API 全量：任务一 3,552 实体、任务二 291/291 篇 563 竞标 | `run/full_api_20260827/`、`run/data/full_api_20260827.db` |
| v0.2（展示中） | Parser 2.1 + 本地 9B 批处理 + 4B 上传样本：任务一 3,185 实体/263 篇、任务二 283 项目/509 竞标 | `run/v0.2_local_20260828/`、`run/data/v0.2_local_20260828.db`、`run/parser_2_1_20260828/` |
| 金标 | 20 篇 128 条（单人标注种子） | `dataset_build/gold/` |
| 银标 | 116 篇 2,315 条（DeepSeek API） | `dataset_build/silver/` |

质量说明：`run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md`；全量验收：`run/full_api_20260827/FULL_PIPELINE_REPORT.md`。不要覆盖以上任一目录或数据库。

## 快速启动

开发前端（Vite `5173` + 后端 `8000`，浏览器走 `http://127.0.0.1:5173/`）：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
cd frontend ; npm.cmd run dev
```

演示/生产形态（单端口托管 `frontend/dist`）：`npm run build` 后 `scripts/run_server.py`，访问 `http://127.0.0.1:8000/`。完整命令表见 `HANDOFF.md`。

## 目录

| 目录 | 用途 |
|---|---|
| `config/` | API 模型配置（`llm_config.yaml`，Key 走环境变量） |
| `docs/` | 模块文档、赛题差距分析 |
| `dataset_build/` | 自建数据集镜像、Blocks、金标、银标、规则基线 |
| `src/` | 后端核心（parsing / extraction / agents / relation / api / services） |
| `frontend/` | Vue 3 前端 |
| `scripts/` | 解析、抽取、评估、平台启动脚本（含 crawl 抓取工具链） |
| `tests/` | 单元、集成、评估用例（59 项） |
| `run/` | 运行产物：数据库、全量结果、日志、上传暂存 |
| `third_party/` | 项目内 LibreOffice（老格式转换依赖） |
