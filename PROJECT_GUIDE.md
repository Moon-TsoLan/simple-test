# 招采标讯实体挖掘与关系分析建模——项目总指导书

> 状态日期：2026-09-17。页面展示为 v0.2 库（9B 批处理 + 4B 上传样本）+ Parser 2.1 Blocks；上传流水线已接通。**方向调整：数据集将切换为官方约 1000 条；处理流水线切换为外部 API 并在此基础上优化；测试以处理流程正常为准。** 新会话先读 `HANDOFF.md`；最新赛题差距见 `docs/GAP_ANALYSIS_最新赛题对照_20260917.md`。

## 1. 项目目标

对应"中国电子杯"第三届ICT大赛赛题五（中国软件命题，2026-09版），构建招采标讯分析系统：

1. **任务一（40分）**：从公告HTML和ZIP附件提取7字段（产品服务名称、品目、品牌（产品供应商）、规格型号、单价、数量、总价），覆盖率/提取率/准确性（准确率×0.4+精确率×0.3+召回率×0.3）/处理速率四项评分；
2. **任务二（20–25分）**：构建采购单位-中标供应商-投标参与方关系模型，实现五个业务场景；**场景结果与官方基准比对，不一致即0分**；
3. **任务三（20–25分）**：Vue+Python平台，批量上传自动处理、全字段检索、五场景可视化；查询效率按"前端发起至渲染完毕"计时，<1秒满分；
4. 综合指标（20分决赛）：过程性文档、设计文档、汇报演示——**权重在决赛翻倍，当前完全未启动**。

关键约束：必须使用 Qwen/DeepSeek 系列开源国产大模型并声明版本与参数规模；评测在命题方云平台+平台提供的模型资源上进行。

## 2. 当前总状态

| 模块 | 当前代码 | 当前产物 | 状态 |
|---|---|---|---|
| 原始数据 | 抓取/镜像同步脚本 | 291篇HTML、243附件ZIP（`dataset_build/mirror_task1|task2/`；原始crawl目录已清理） | 自建开发集，将切换官方数据 |
| Block解析 | Parser 2.1.0 | `dataset_build/blocks/`=2.0.0（274,597）；`run/parser_2_1_20260828/`=2.1.0（274,586） | 双目录并存，勿混淆 |
| 本地筛选 | 代码1.3.1 / 产物1.3.0 | 291篇→3,716来源Blocks、1,411请求 | 金标证据召回100% |
| 任务一 | Agent 2.1.0 | v0.1 API全量3,552实体；v0.2本地9B 3,184实体（262篇） | 20篇金标：v0.1严格一致87.5%，v0.2为81.25% |
| 时序联网核验 | Verifier 1.0.0 | "新华三"小样本 | 工程可用，未全量 |
| 任务二 | Relation Agent 1.4.0 / 1.5.2+SlotPacker | v0.1：291项目/563竞标；v0.2：282/291篇508竞标 | 无人工关系金标 |
| 任务三 | FastAPI+Vue3+SQLite | 上传流水线已接通（SSE）；检索/导出/五场景/图谱全量通过 | 查询效率未按官方口径实测 |
| 本地模型 | LM Studio qwen3.5-9b（批处理）/ qwen3-4b-2507（上传运行时）@127.0.0.1:1234 | — | 降级为离线备份 |
| 自动化测试 | pytest 59项 + compileall + Vue构建 | 全部通过 | 缺多轮并发P95 |

## 3. 整体架构

```text
HTML + 附件ZIP
  → Parser 2.1多格式提取、安全递归解包、原生PDF水印过滤、OCR
  → 统一Block JSON（稳定内容寻址ID、来源坐标）
  → Selector 1.3本地筛选与请求分块
  → 任务一LangGraph Agent 2.1
       ├─ 强表规则快速通道（可靠表头映射+产品信号同时成立）
       └─ 弱表/正文：模型抽取（外部API或本地OpenAI兼容）
  → Schema/证据/金额校验、最多一次修复
  → 公告级来源过滤、去重与冲突处理
  → 任务一JSON

同一批Blocks → 任务二候选抽取 → Relation Agent 1.5（含SlotPacker与超大强表本地通道）
  → Pydantic与Block坐标校验 → 任务二JSON

任务一 + 任务二结果 → SQLite（WAL+六张预计算表）→ FastAPI → Vue检索/导出/五场景/项目图
上传流水线：src/api/pipeline.py 把 HTML/ZIP 跑完 Parser → Selector/SlotPacker → Agent → SQLite
```

## 4. 技术栈

| 层级 | 技术 |
|---|---|
| 运行环境 | Windows、Conda `Aproject`、Python 3.11 |
| 文档解析 | lxml、python-docx、openpyxl、xlrd、PyMuPDF、Pillow、RapidOCR、项目内LibreOffice 26.2.5 |
| 智能体 | LangGraph 1.x、OpenAI兼容Chat、Pydantic v2 |
| 业务存储 | SQLite WAL、索引、六张预计算关系表 |
| 后端/前端 | FastAPI、Uvicorn / Vue 3、TypeScript、Vite、ECharts |
| 导出/测试 | CSV、openpyxl XLSX / pytest、TestClient、vue-tsc |
| 小样本搜索 | DDGS（不替代权威工商登记） |

## 5. 数据与版本契约

- 官方数据到达后编写薄适配器，只把官方目录映射为 `mirror_task1` 同构输入（HTML+ZIP 一一对应），不改核心流水线；
- Block契约、字段Schema、金额口径等详见 `docs/BLOCK_PARSER.md` 与 `block转化流程.md`；
- 概念7字段对应工程Schema：`product_service_name / category_name / category_code / brand_supplier / spec_model / unit_price / quantity / quantity_unit / total_price / evidence_refs`；缺证据必须为 `null`；金额统一为元。

## 6. 模型与API策略（2026-09-17 调整）

- **评测路线**：处理流水线切换为外部 API（OpenAI 兼容），优先使用赛事平台提供的标准模型资源；需在文档中声明模型版本与参数规模；
- **本地路线**：LM Studio Qwen 模型保留为离线备份，不再作为主路线迭代；
- 外部API调用规则不变：密钥只走环境变量、显式 `--allow-external-api`、调用次数与Token硬上限、先小样本后扩大、输出记录实际用量；旧API密钥曾暴露，必须轮换；
- API历史用量参考：任务一708次/122.8万Token；任务二400次/400万Token。

## 7. 运行入口

```powershell
# Block解析 / Selector
conda run -n Aproject python scripts/parse_blocks.py --workers 4
conda run -n Aproject python scripts/select_blocks.py --overwrite

# 任务一 / 任务二（backend: rules | api | local | replay）
conda run -n Aproject python scripts/run_entity_agent.py --backend rules
conda run -n Aproject python scripts/run_relation_agent.py --backend rules --limit 20

# 平台开发形态（Vite 5173 + 后端 8000）
D:\anaconda\envs\Aproject\python.exe scripts/run_server.py --host 127.0.0.1 --port 8000
cd frontend ; npm.cmd run dev

# 生产形态
cd frontend ; npm run build
conda run -n Aproject python scripts/run_server.py   # 默认读 v0.2 库 + Parser 2.1 Blocks
```

切换 v0.1 冻结库：`--db run/data/full_api_20260827.db --block-dir dataset_build/blocks/notices`。仅规则通道：`--pipeline-backend rules`。不要对冻结库重跑 `init_app_db.py`。

## 8. 测试与效果口径

```powershell
conda run -n Aproject python -m pytest -q --basetemp run/pytest_tmp -o cache_dir=run/pytest_cache
conda run -n Aproject python -m compileall -q src scripts
cd frontend ; npm run build
```

最近一次：**59项pytest**、compileall、Vue构建全部通过。**当前阶段测试目标：验证处理流程正常（数据集更换+API切换后流水线无损），不在自建集上追求质量指标。**

以下数字不能当正式准确率：20篇单人金标回归、4篇Replay、8实体小库延迟。正式结论需官方口径三指标评测、双人金标、真实规模P50/P95。

## 9. 风险

1. 官方数据适配器未写；官方约1000条的处理吞吐未验证（外部API切换是前提）；
2. 任务二无人工金标，五场景结果与官方基准的一致性未知（口径需可配置对齐）；
3. `category_code` 误填品目号（4B已复现），正撞评分字段；
4. v0.2 有任务一29篇空实体、任务二9篇失败（本地请求失败所致，API路线下需复测）；
5. 提取准确性需按官方公式（准确率/精确率/召回率）建立评测脚本；
6. 查询效率未按"含前端渲染"口径实测；
7. 提交物（PPT/双视频/设计文档/过程性文档）完全未启动，决赛权重翻倍；
8. 金标单人标注、规模小；Evaluator 登录账号与云平台部署方案未定；
9. Neo4j/图检索增强为赛题推荐项，当前为 SQLite 预计算表（选型辩护或低成本投影层二选一）。

## 10. 推荐实施顺序

1. 官方数据薄适配器 + 数据集切换；
2. 流水线后端切外部 API（OpenAI 兼容，代码已支持 `--backend api`），加并发与批量，验证1000条级吞吐；
3. 回归验证处理流程正常（pytest + 上传链路），修复 `category_code` 品目号 bug；
4. 按官方公式建立准确性评测脚本；补任务二人工关系金标；
5. 查询效率按官方口径（含前端渲染）实测五场景；
6. 技术路线对比分析报告 + 数据质量分析报告（素材已齐，先成文）；
7. Neo4j 投影层（可选增强）；云平台部署包（Linux 一键启动、评审账号）；
8. 设计文档、PPT、双视频、提交包。

## 11. 文档入口

- 新会话交接：`HANDOFF.md`
- 文档职责与事实源规则：`docs/README.md`
- 最新赛题差距分析：`docs/GAP_ANALYSIS_最新赛题对照_20260917.md`
- Block运行流程：`block转化流程.md`；Block技术契约：`docs/BLOCK_PARSER.md`
- Selector：`docs/MODEL_INPUT_SELECTOR.md`；任务一Agent：`docs/ENTITY_EXTRACTION_AGENT.md`
- 任务二：`docs/TASK2_RELATION_SYSTEM.md`；任务三：`docs/TASK3_PLATFORM.md`
- v0.1全量验收：`run/full_api_20260827/FULL_PIPELINE_REPORT.md`；v0.2质量：`run/v0.2_local_20260828/QUALITY_AND_DISPLAY.md`
