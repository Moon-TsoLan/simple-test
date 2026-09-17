# 官方数据集薄适配器

把命题方发放的约 1000 条 HTML+ZIP 映射为项目统一输入，不改 Parser / Selector / Agent。

```text
<output>/
  notices/{id}.html
  attachments/{id}.zip
  manifest.json
  id_map.csv
```

与 `dataset_build/fake_official_data/` 契约相同。抽取实验请另开 `run/` 目录。

## 用法

```powershell
python scripts/adapt/official_adapter.py --source <解压根目录> --output dataset_build/official_adapted --layout auto
```

`--layout`：

| 值 | 含义 |
|---|---|
| `auto` | 依次探测下面三种 |
| `split_dir` | `notices/`+`attachments/`，或 `html/`+`zip/`，同文件名 stem 成对 |
| `paired` | 同一目录下 `{id}.html` 与 `{id}.zip` |
| `per_folder` | 每篇一个子目录，内含一个 html 和一个 zip |

## 自测

用假官方集（或测试夹具）再跑一遍适配器，核对 `html_sha256` / `zip_sha256` 与源文件一致即可，不必跑抽取。
