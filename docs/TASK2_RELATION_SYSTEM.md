# 任务二：用户画像与竞争合作关系系统

## 1. 当前结论

任务二的工程链路已经实现：统一 Block 输入可以先经过确定性候选抽取，再由受控关系智能体调用本地 OpenAI 兼容模型，输出经 Pydantic 与证据回指校验的项目关系 JSON；确认结果写入 SQLite，刷新六张预计算表，并通过五类场景 API 与项目子图 API 查询。

2026-08-27已用外部API完成291篇全量工程验证：291/291成功，最终303个包件、563条竞标关系、1,009个机构；563条关系都有证据，1,234个Block/行引用全部有效。Relation Agent当前为1.4.0，最终结果位于`run/full_api_20260827/relation_api/`。

任务二仍没有人工关系金标，因此只能声明“全量结构、证据和功能闭环通过”，不能把Schema通过率或证据有效率表述为关系准确率。最终本地模型也尚未完成同口径回归。

2026-08-26 已增加4篇真实公告的 Codex 模型替代闭环：4/4关系结果通过 Schema 与证据回指校验，独立库包含4个项目、6条竞标记录，五个场景均得到非空测试结果。该结果验证工程链路，不是本地模型效果结论，详见 `dataset_build/pilot/model_substitute_20260826/README.md`。

## 2. 技术选型

| 层级 | 当前选型 | 原因 |
|---|---|---|
| 数据契约 | Pydantic v2 | 严格字段、枚举、金额与行号约束，模型与规则共用同一 Schema |
| 关系权威库 | SQLite（WAL） | 免部署、可离线、事务和索引完整，适合比赛现场 |
| 统计计算 | SQLite 六张预计算表 | 避免页面实时做复杂全图聚合 |
| 图谱展示 | 从 SQLite 按项目投影子图 | 当前零外部依赖即可展示；Neo4j/Kuzu 作为可选展示后端，不影响统计查询 |
| 抽取方式 | 确定性候选层 + 受控关系智能体 + 本地模型 | 候选层不冒充高准确结果；模型只负责有证据的结构化判断 |
| 主体归一化 | NFKC、空白/标点归一化、稳定哈希 ID、相似名称审核队列 | 只自动合并规范化后完全一致的名称，避免误合并 |

不采用 NetworkX 作为运行前置；当前不要求部署 Neo4j。以后若比赛展示需要，可把同一 SQLite 关系表批量同步到 Neo4j/Kuzu，而无需修改抽取 Schema 和五场景接口。

## 3. 两级抽取流程

```text
任务二公告 Block JSON
  → 确定性规则识别项目编号、采购单位、代理机构和竞标表
  → 形成 candidate_only 候选（可审计，不默认入库）
  → 选择含供应商/报价/得分/排名/审查结果的证据 Block
  → 本地 OpenAI 兼容模型输出 ProjectRelationInput
  → Pydantic Schema 校验
  → notice_id、block_id、block_row 证据回指校验
  → 文本行号清空、越界表格行按供应商名称唯一回定位
  → 最多一次受控修复
  → [≥80条强结构投标记录] 跳过模型复述，使用本地超大强表通道
  → 成功结果按 notice_id 幂等写入 SQLite
  → 刷新六张预计算表
  → 五场景 API / 项目子图 API
```

当模型没有配置时，智能体返回 `candidate_only`，调用次数为 0。只有模型校验成功结果，或操作者显式使用 `--commit-candidates`，才会写入关系库。

## 4. 数据模型

核心输入由以下 Pydantic 模型组成：

- `ProjectRelationInput`：公告、项目编号、采购方式、日期、采购单位、代理机构；
- `PackageInput`：包号、包件名称、竞标记录、产品；
- `BidInput`：主体、报价、得分、排名、资格审查、符合性审查、结果和证据坐标；
- `ProductInput`：产品、品目代码、品牌、规格型号和产品供应商；
- `OrganizationInput`：主体名称与角色。

SQLite 原始表包括 `organizations / org_aliases / projects / project_units / packages / bids / products / package_products / alias_review_queue`。

六张预计算表：

1. `unit_win_stats`：采购单位 × 中标供应商；
2. `unit_bidder_stats`：采购单位 × 投标主体；
3. `unit_cobid_pairs`：采购单位下两两共同投标；
4. `supplier_cobid`：中标供应商 × 共同竞标主体；
5. `supplier_common_units`：供应商对 × 共同采购单位；
6. `supplier_joint_projects`：供应商对 × 同包件共同参与项目。

金额统一使用元。统计中的“总金额”仅累计中标或成交金额；场景五的 `participant_amount_yuan` 是所选主体在共同包件中的报价合计，字段名已明确区分。

## 5. 五个业务场景

| 场景 | 接口 | 实现方式 |
|---|---|---|
| 采购单位 → 中标供应商 | `GET /api/task2/units/{unit_id}/win-suppliers` | `unit_win_stats` |
| 采购单位 → TOP 投标人与共同投标组合 | `top-bidders`、`co-bid-pairs` | 两张预计算表 |
| 中标供应商 → 共同竞标主体 | `GET /api/task2/suppliers/{supplier_id}/co-bidders` | `supplier_cobid` |
| 多供应商 → 共同采购单位 | `GET /api/task2/suppliers/common-units?ids=...` | 原始关系受控交集查询，支持两个以上主体 |
| 多供应商 → 共同参与项目 | `GET /api/task2/suppliers/joint-projects?ids=...` | 原始关系受控交集查询，支持两个以上主体 |

项目下拉和图谱接口：

- `GET /api/task2/projects`
- `GET /api/task2/organizations`
- `GET /api/task2/aliases/review`
- `GET /api/task2/graph/subgraph?project_id=...`
- `POST /api/task2/extract-candidate`
- `POST /api/task2/projects`

## 6. 运行方法

只生成规则候选，不调用模型、不写关系库：

```powershell
conda run -n Aproject python scripts/run_relation_agent.py --backend rules --limit 20
```

本地模型服务就绪后运行。默认读取 `config/llm_config.yaml` 的 `local` 段（当前为 LM Studio `http://127.0.0.1:1234`）；可用 `--base-url` / `--model` 覆盖。小样本必须设置调用和 Token 硬上限，且不要 `--commit` 到正式库：

```powershell
conda run -n Aproject python scripts/run_relation_agent.py `
  --backend local `
  --max-model-calls 2 `
  --max-total-tokens 24000 `
  --ids 20260813_27128600 `
  --output-dir run/local_lmstudio_20260828/relation_probe/notices
```

显式提交规则候选仅用于调试，不应作为正式关系数据：

```powershell
conda run -n Aproject python scripts/run_relation_agent.py --backend rules --commit-candidates --limit 5
```

## 7. 已验证与待验证

已通过合成测试：Schema、主体完全规范化去重、幂等重跑、六张聚合表、五场景查询、项目子图、空库行为、模型输出证据校验和一次修复。

291篇外部API全量验证：

- 291/291篇成功；198篇直接模型成功、92篇一次修复成功、1篇超大强表本地成功；
- 最终有效结果382次调用、3,705,708 Token；含失败重试的历史用量400次、4,004,392 Token；
- 291篇都有竞标记录，287篇有明确中标/成交关系；
- 290篇有采购单位，289篇有代理机构；
- 450条关系有金额、335条有得分、368条有排名；
- 全量隔离数据库和六类接口样本均返回非空结果，关系查询单次约2.5–4.2ms。

仍待完成：

- 至少 200 篇含投标/得分/审查表公告的人工抽检；
- 五个场景各 20 条人工确认断言；
- 主体别名审核集和误合并率；
- 多轮并发查询 P50/P95；
- 本地模型字段级准确率、失败率与单篇耗时。
