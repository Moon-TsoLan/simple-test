# -*- coding: utf-8 -*-
"""按 URL 定向补抓公告（HTML + 全部附件），用于补齐稀有附件扩展名。

用法：
    python scripts/crawl/fetch_urls.py
    python scripts/crawl/fetch_urls.py --urls http://... http://...
    python scripts/crawl/fetch_urls.py --url-file urls.txt
"""
import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crawl import download_ccgp as dc  # noqa: E402

DEFAULT_URLS = [
    # xlsx
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202608/t20260814_27137040.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260723_26991563.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202608/t20260804_27071201.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260706_26876573.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202605/t20260509_26536325.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260629_26835308.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260609_26714193.htm",
    # xls
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260715_26937648.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202604/t20260429_26479131.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202603/t20260327_26329189.htm",
    "https://www.ccgp.gov.cn/cggg/dfgg/zbgg/202605/t20260509_26532508.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260618_26775283.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202502/t20250219_24187784.htm",
    # rar
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202606/t20260625_26813609.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202606/t20260610_26722058.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202605/t20260522_26614221.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202607/t20260717_26951997.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202603/t20260323_26298573.htm",
    "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202511/t20251113_25686854.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202412/t20241217_23892691.htm",
    "https://www.ccgp.gov.cn/cggg/zygg/zbgg/202503/t20250307_24261292.htm",
    # jpg
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202608/t20260814_27131841.htm",
    "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/202608/t20260813_27128600.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202608/t20260813_27125840.htm",
    "http://www.ccgp.gov.cn/cggg/zygg/zbgg/202605/t20260514_26566185.htm",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--url-file", default="")
    ap.add_argument("--att-delay-min", type=float, default=0.5)
    ap.add_argument("--att-delay-max", type=float, default=1.0)
    args = ap.parse_args()

    urls = list(args.urls)
    if args.url_file:
        urls += [ln.strip() for ln in Path(args.url_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not urls:
        urls = DEFAULT_URLS

    manifest = dc.load_manifest()
    seen = dc.load_state("seen.json")
    failed = dc.load_state("failed.json")
    session = dc.SafeSession(retries=3, backoff=30)
    fake_args = SimpleNamespace(
        mode="all", force=False,
        att_delay_min=args.att_delay_min, att_delay_max=args.att_delay_max,
    )

    for i, url in enumerate(urls, 1):
        m = dc.DETAIL_RE.search(url)
        if not m:
            print("SKIP_URL", url)
            continue
        nid = f"{m.group(2)}_{m.group(3)}"
        prev = seen.get(nid, {})
        if prev.get("status") == "ok" and prev.get("html_ok"):
            print(f"[SKIP] {i}/{len(urls)} {nid} 已存在")
            continue
        item = {
            "notice_id": nid,
            "url": url,
            "source_key": "targeted",
            "source_type": "定向补缺",
            "title": url,
        }
        print(f"[START] {i}/{len(urls)} {nid} {url}")
        try:
            ok = dc.process_notice(session, item, fake_args, manifest, seen, failed)
            print("OK" if ok else "FAIL", nid)
        except Exception as exc:
            print("ERR", nid, exc)
        time.sleep(dc.random.uniform(1.0, 2.0))

    counts = dc.attachment_ext_counts(manifest)
    print("FINAL", len(manifest["notices"]), dict(sorted(counts.items())))
    print("MANIFEST", dc.MANIFEST_DIR / "manifest.json")


if __name__ == "__main__":
    main()
