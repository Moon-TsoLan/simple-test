# 数据抓取脚本使用说明

## 环境

- Python 3.10+
- 依赖：`requests`、`lxml`（当前机器已安装；如缺失执行 `pip install -r requirements.txt`）

## 命令

```powershell
cd D:\all_contest\2026_8_15

# 完整抓取（HTML + 附件 + 打包 zip）
python scripts/crawl/download_ccgp.py --mode all --max-pages 2 --max-notices 150

# 只抓 HTML
python scripts/crawl/download_ccgp.py --mode html --max-pages 3 --max-notices 200

# 只补附件（对已抓 HTML 的公告）
python scripts/crawl/download_ccgp.py --mode attachments --max-pages 2 --max-notices 150

# 只收集列表，查看候选
python scripts/crawl/download_ccgp.py --mode list --sources dfgg/zbgg --max-pages 1
```

## 栏目说明

`--sources` 支持（逗号分隔）：

| key | 栏目 |
|---|---|
| `dfgg/zbgg` | 地方中标公告 |
| `zygg/zbgg` | 中央中标公告 |
| `dfgg/cjgg` | 地方成交公告 |
| `zygg/cjgg` | 中央成交公告 |

## 输出

| 内容 | 位置 |
|---|---|
| 公告原始 HTML | `dataset_build/crawl/html/{YYYYMMDD}/{notice_id}.html` |
| 公告解析 JSON | `dataset_build/crawl/html/{YYYYMMDD}/{notice_id}.json` |
| 附件原始文件 | `dataset_build/crawl/attachments/{notice_id}/` |
| 一篇公告一个 zip | `dataset_build/crawl/attachments/{notice_id}.zip` |
| 官方同构镜像 | `dataset_build/mirror_task1/notices`、`dataset_build/mirror_task1/attachments` |
| 总清单 | `dataset_build/manifests/manifest.json`、`manifest.csv` |
| 断点状态 | `dataset_build/crawl/state/seen.json`、`failed.json` |
| 日志 | `dataset_build/crawl/logs/download_ccgp.log` |

## 行为说明

1. 重复运行自动跳过已完成公告（`state/seen.json`），支持断点续抓。
2. 失败自动重试 3 次，遇到 403/反爬页退避 60 秒。
3. 详情页与附件请求使用同一 Session，附件走 `download.ccgp.gov.cn/oss/download?uuid=...`。
4. zip 内保留原始文件名，并附加 `_files_manifest.json` 记录来源 URL、大小、SHA-256。
5. 只采集公告列表主区（`ul.c_list_bid`），不会误抓新闻/法规边栏。

## 后续增量

- 抓取更多数据：增大 `--max-pages`（每栏目每页约 20 条）或 `--max-notices`。
- 官方数据发布后：写 `scripts/adapt/official_adapter.py`，把官方压缩包映射到 `mirror_task1` 同构目录。
