# -*- coding: utf-8 -*-
"""删除历史误抓的非 /cggg/ 栏目文件（新闻/法规边栏）。

依据 crawl/html 下每个 notice 的 *.json 中 url 字段判断；
只删除 url 不含 /cggg/ 的公告对应的 html/json/zip/附件目录/镜像文件。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML_DIR = ROOT / "dataset_build" / "crawl" / "html"
ATTACH_DIR = ROOT / "dataset_build" / "crawl" / "attachments"
MIRROR_NOTICES = ROOT / "dataset_build" / "mirror_task1" / "notices"
MIRROR_ATTACH = ROOT / "dataset_build" / "mirror_task1" / "attachments"


def unlink(p: Path):
    if p.exists():
        p.unlink()
        print("删除", p)


def main():
    n = 0
    for json_file in HTML_DIR.rglob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "/cggg/" in data.get("url", ""):
            continue
        n += 1
        notice_id = json_file.stem
        date_dir = json_file.parent
        unlink(json_file)
        unlink(date_dir / f"{notice_id}.html")
        unlink(ATTACH_DIR / f"{notice_id}.zip")
        att_dir = ATTACH_DIR / notice_id
        if att_dir.exists():
            for f in att_dir.iterdir():
                f.unlink()
            att_dir.rmdir()
            print("删除目录", att_dir)
        unlink(MIRROR_NOTICES / f"{notice_id}.html")
        unlink(MIRROR_ATTACH / f"{notice_id}.zip")
    print("清理完成", n, "条")


if __name__ == "__main__":
    main()
