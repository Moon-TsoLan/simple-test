# 任务三：Vue + Python 可视化检索平台

## 1. 当前结论

任务三已形成可本地运行的单端口系统：FastAPI 提供数据、任务、导出和关系分析接口；Vue 3 提供数据导入、任务一检索、任务二五场景、项目图谱和系统状态页面；SQLite 保存任务一实体、任务状态和任务二关系数据；Vue 构建产物由 FastAPI 直接托管。

当前模型未就绪，因此原始HTML/ZIP上传完成后仍停在`staged / ready_for_pipeline`。这是显式等待状态，不代表已经完成解析或抽取。

2026-08-27已建立不覆盖旧正式库的全量隔离库`run/data/full_api_20260827.db`：任务一291篇/3,552条实体，任务二291项目/303包件/563条竞标关系。检索、证据回读、全量CSV/XLSX、五场景、项目图和Vue生产构建均通过。机器报告为`run/full_api_20260827/platform_verification.json`。

另有一个与正式库隔离的4篇公告试运行库 `run/data/pilot_model_substitute_20260826.db`。它使用 Codex 人工响应替代本地模型，已验证首页、检索、证据回读、CSV导出、五场景和图谱；启动方法见 `dataset_build/pilot/model_substitute_20260826/README.md`。

## 2. 技术选型

| 模块 | 选型 |
|---|---|
| 后端 | FastAPI + Pydantic v2 + Uvicorn |
| 前端 | Vue 3 + TypeScript + Vite + Vue Router |
| 可视化 | ECharts（按需加载柱状图与关系图） |
| 业务存储 | SQLite WAL |
| 后台任务 | FastAPI BackgroundTasks + SQLite 任务表 |
| 文件导出 | Python CSV + openpyxl XLSX |
| 部署 | Vue `dist/` 由 FastAPI 静态托管，单端口 |

当前规模不引入 Celery、Redis、独立图数据库或前后端双服务部署，减少比赛现场的故障点。

## 3. 页面与功能

### 数据导入

- 选择任务一或任务二；
- 批量上传 HTML、ZIP、JSON、JSONL；
- 文件名安全化和重复名检查；
- 单文件 200 MB、单批 500 MB 上限；
- 文件逐块落盘，避免一次把大文件读入内存；
- SQLite 记录任务、文件状态、成功/失败数；
- SSE 与任务详情接口已提供；
- 模型未就绪时明确显示“文件已暂存，等待流水线”。

### 任务一检索

- 全字段、公告编号、产品、品牌、品目、来源文件筛选；
- 后端分页，单页最多 100 条；
- 实体详情和 `block_id + block_row` 证据定位；
- 详情按需回读 Block JSON，显示原文表格行或文本摘录；
- CSV/XLSX 全量导出，不受列表 100 条上限截断。

### 任务二场景

- 五个场景统一选择表单；
- 单主体和多主体查询；
- 结果表和 ECharts 柱状图；
- 场景二同时展示 TOP 投标主体和共同投标组合；
- 数据库为空时显示真实空状态。

### 关系图谱

- 选择已入库项目；
- 展示项目、采购单位、代理机构、包件、中标供应商、投标参与方、产品和产品供应商；
- 图由 SQLite 权威表即时投影，不要求 Neo4j 才能运行。

### 系统状态

- 任务一公告和实体计数；
- 任务二项目、主体、包件和竞标记录计数；
- 最近处理任务；
- 模型未配置状态；
- “已验证”与“待真实数据验证”的能力边界。

## 4. 主要接口

```text
GET  /api/health
GET  /api/status
POST /api/admin/import-task1
GET  /api/task1/items
GET  /api/task1/items/{entity_id}
GET  /api/task1/export.csv
GET  /api/task1/export.xlsx
POST /api/jobs/upload
GET  /api/jobs/{job_id}
POST /api/jobs/{job_id}/retry
GET  /api/jobs/{job_id}/events
```

任务二接口见 `docs/TASK2_RELATION_SYSTEM.md`。

## 5. 初始化与启动

前端依赖与构建：

```powershell
cd D:\all_contest\2026_8_15\frontend
npm install
npm run build
```

初始化隔离数据库并导入任务一、任务二全量结果：

```powershell
cd D:\all_contest\2026_8_15
conda run -n Aproject python scripts/init_app_db.py `
  --db run/data/full_api_20260827.db `
  --import-task1 `
  --task1-dir run/full_api_20260827/agent2_curated/notices `
  --relation-dir run/full_api_20260827/relation_api/notices
```

启动单端口系统：

```powershell
$env:APP_DB_PATH = "run/data/full_api_20260827.db"
conda run -n Aproject python scripts/run_server.py --host 127.0.0.1 --port 8000
```

浏览器访问 `http://127.0.0.1:8000/`。

前端开发模式可单独运行 `npm run dev`，Vite 会把 `/api` 转发到 8000 端口。

## 6. 测试与当前边界

`pytest.ini` 已把测试发现范围固定为 `tests/`，避免工作区运行产物或受保护临时目录被误收集：

```powershell
conda run -n Aproject python -m pytest -q
```

当前验证包括：

- 空数据库、404、参数错误和重复上传文件名；
- 125 条任务一实体的分页、详情和不截断 CSV/XLSX 导出；
- 任务二五场景和图谱接口；
- 上传暂存状态；
- Vue TypeScript 检查与生产构建；
- FastAPI 托管首页及健康、状态接口。

291篇全量验收还包括：

- 3,552个任务一主证据坐标和4,085个补充引用全部有效；
- 563条任务二关系均有证据，1,234个引用全部有效；
- CSV与XLSX均完整导出3,552行；
- 全量库六类关系查询及项目图均返回非空结果；
- 单次任务一搜索约8ms、关系查询约2.5–4.2ms、全量XLSX约0.60s；
- 58项pytest、Python编译检查和Vue生产构建通过。

当前Vue生产构建通过；ECharts关系图相关分包约508KB，Vite会给出大于500KB的体积警告，但不影响构建和运行。只有正式演示中出现明显首屏或图谱加载问题时，再使用动态导入或`manualChunks`拆包。

尚不能声明完成：

- 原始上传到模型抽取再到可检索结果的完整真实闭环；
- 任务二人工金标准确率；
- 多轮并发查询 P95 小于 1 秒；
- 模型吞吐量和并发稳定性。

这些项目应在模型下载完成、任务二真实数据准备充分后再测试和打勾。
