# 数据抓取脚本使用说明

## 环境

- Python 3.10+
- 依赖：`requests`、`lxml`（`pip install -r scripts/crawl/requirements.txt`）

## 假官方集（推荐：赛题包装对照台）

从 [中国政府采购网](https://www.ccgp.gov.cn/) 按赛题 **HTML+ZIP 配对** 抓约 100 条，写入独立目录，**不覆盖**旧 `mirror_task1` / 冻结库，也**不跑**现有 Parser/Selector/Agent。

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/crawl/build_fake_official.py --target 100
```

只看列表、不下附件：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/crawl/build_fake_official.py --list-only
```

已有 `_crawl` 时只落盘：

```powershell
D:\anaconda\envs\Aproject\python.exe scripts/crawl/build_fake_official.py --materialize-only
```

输出：

```text
dataset_build/fake_official_data/
  notices/{notice_id}.html
  attachments/{notice_id}.zip
  manifest.json
  quality_report.md
  REJECTS.jsonl
  _crawl/                 # 原始抓取与断点，勿当抽取输入
```

入选只看：结果类中标/成交栏目、标题不是废标/流标/终止/更正/澄清/延期、HTML 与同 ID 非空 ZIP 一对。不按现有强表或七字段规则筛选。本集是后续多种识别方法的共同输入；抽取结果请写到 `run/`，不要写回本目录。

## 通用抓取（旧入口）

```powershell
# 完整抓取（默认仍会镜像到 mirror_task1）
python scripts/crawl/download_ccgp.py --mode all --max-pages 2 --max-notices 150

# 隔离输出、不写旧镜像
python scripts/crawl/download_ccgp.py --mode all --output-root dataset_build/fake_official_data/_crawl --no-mirror --stop-after-paired 100
```

## 栏目说明

`--sources` 支持（逗号分隔）：

| key | 栏目 |
|---|---|
| `dfgg/zbgg` | 地方中标公告 |
| `zygg/zbgg` | 中央中标公告 |
| `dfgg/cjgg` | 地方成交公告 |
| `zygg/cjgg` | 中央成交公告 |

## 输出（默认 crawl 根目录）

| 内容 | 位置 |
|---|---|
| 公告原始 HTML | `dataset_build/crawl/html/{YYYYMMDD}/{notice_id}.html` |
| 公告解析 JSON | `dataset_build/crawl/html/{YYYYMMDD}/{notice_id}.json` |
| 附件原始文件 | `dataset_build/crawl/attachments/{notice_id}/` |
| 一篇公告一个 zip | `dataset_build/crawl/attachments/{notice_id}.zip` |
| 官方同构镜像 | `dataset_build/mirror_task1/notices`、`dataset_build/mirror_task1/attachments`（`--no-mirror` 时不写） |
| 总清单 | 默认 `dataset_build/manifests/`；`--output-root` 时为该目录下 `manifests/` |
| 断点状态 | `{output-root}/state/seen.json`、`failed.json` |

## 行为说明

1. 重复运行自动跳过已完成公告（`state/seen.json`），支持断点续抓。
2. 失败自动重试 3 次，遇到 403/反爬页退避。
3. 详情页与附件请求使用同一 Session，附件走 `download.ccgp.gov.cn/oss/download?uuid=...`。
4. zip 内保留原始文件名，并附加 `_files_manifest.json` 记录来源 URL、大小、SHA-256。
5. 只采集公告列表主区（`ul.c_list_bid`），不会误抓新闻/法规边栏。

## 正式约 1000 条

官方压缩包解压后：

```powershell
python scripts/adapt/official_adapter.py --source <解压根目录> --output dataset_build/official_adapted --layout auto
```

输出同样是 `notices/` + `attachments/` + `manifest.json`。说明见 [../adapt/README.md](../adapt/README.md)。
