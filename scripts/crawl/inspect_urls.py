# -*- coding: utf-8 -*-
"""查看一批公告 URL 的附件类型，用于定向补缺。"""
import sys
import time
from pathlib import Path

import requests
import lxml.html

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# 复用主爬虫的解析函数（不触发 main）
from crawl import download_ccgp as dc  # noqa: E402

URLS = [
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202608/t20260814_27137040.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202608/t20260814_27137425.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260723_26991563.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202608/t20260804_27071201.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260706_26876573.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202605/t20260509_26536325.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260629_26835308.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260609_26714193.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260715_26937648.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202604/t20260429_26479131.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202603/t20260327_26329189.htm",
    "https://www.ccgp.gov.cn/cggg/dfgg/zbgg/202605/t20260509_26532508.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260618_26775283.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202502/t20250219_24187784.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260625_26813609.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202606/t20260610_26722058.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202605/t20260522_26614221.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260717_26951997.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202603/t20260323_26298573.htm",
    "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202511/t20251113_25686854.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202412/t20241217_23892691.htm",
    "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202503/t20250307_24261292.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202608/t20260814_27131841.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202608/t20260813_27128600.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202608/t20260813_27125840.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202608/t20260814_27139104.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202605/t20260514_26566185.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202608/t20260814_27133843.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202608/t20260813_27125689.htm",
]


def main():
    targets = set(sys.argv[1:]) if len(sys.argv) > 1 else set()
    s = requests.Session()
    s.headers.update(dc.DEFAULT_HEADERS)
    for u in URLS:
        try:
            r = s.get(u, headers={"Referer": "http://www.ccgp.gov.cn/"}, timeout=30)
            info = dc.parse_detail(r.content, u)
            exts = sorted({Path(a.get("name") or "").suffix.lower() for a in info["attachments"]})
            print(u, "|", info["title"][:60], "|", exts)
            if targets:
                hit = [a for a in info["attachments"] if Path(a.get("name") or "").suffix.lower() in targets]
                for a in hit:
                    print("   HIT", a.get("name"), a.get("url"))
        except Exception as exc:
            print(u, "ERR", exc)
        time.sleep(1.5)


if __name__ == "__main__":
    main()
