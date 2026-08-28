# -*- coding: utf-8 -*-
"""修复已下载附件：
1. 重试未下全的 uuid 附件（自动选择 http/https、带/不带连字符候选）；
2. 重打包 zip，解决同名附件冲突。

用法：
    python scripts/crawl/repair_attachments.py --retry
    python scripts/crawl/repair_attachments.py --dedupe-zips
    python scripts/crawl/repair_attachments.py --all
"""
import argparse
import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "dataset_build" / "manifests" / "manifest.json"
STATE = ROOT / "dataset_build" / "crawl" / "state" / "seen.json"
ATTACH_DIR = ROOT / "dataset_build" / "crawl" / "attachments"
HTML_DIR = ROOT / "dataset_build" / "crawl" / "html"
MIRROR_ATTACH = ROOT / "dataset_build" / "mirror_task1" / "attachments"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def uuid_candidates(uuid):
    import re
    compact = re.sub(r"[^0-9a-fA-F]", "", uuid or "")
    ids = []
    if compact:
        ids.append(compact)
        if len(compact) == 32:
            ids.append("-".join([compact[0:8], compact[8:12], compact[12:16], compact[16:20], compact[20:32]]))
    if uuid and uuid not in ids:
        ids.append(uuid)
    if "-" in (uuid or ""):
        schemes = ["http", "https"]
    else:
        schemes = ["https", "http"]
    urls = []
    for scheme in schemes:
        for vid in ids:
            u = f"{scheme}://download.ccgp.gov.cn/oss/download?uuid={vid}"
            if u not in urls:
                urls.append(u)
    return urls


def load_json(p, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save_json(p, data):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_filename(resp, fallback):
    cd = resp.headers.get("Content-Disposition") or ""
    if "filename" in cd:
        import re
        import urllib.parse
        m = re.search(r"filename\*?=(?:UTF-8''|utf-8''|['\"]?)([^;'\"]+)", cd, re.I)
        if m:
            return urllib.parse.unquote(m.group(1))
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
        if m:
            return urllib.parse.unquote(m.group(1))
    return fallback


def safe_name(name, max_len=120):
    import re
    name = re.sub(r'[\\/:*?"<>|\r\n\t\x00-\x1f]+', "_", name or "attachment").strip().strip(".")
    if len(name) > max_len:
        stem, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        name = stem[: max_len - len(ext) - 1] + ("." + ext if ext else "")
    return name or "attachment"


def retry_failed():
    manifest = load_json(MANIFEST, {"notices": {}})
    seen = load_json(STATE, {})
    notices = manifest["notices"]
    fixed = 0
    for nid, n in notices.items():
        atts = n.get("attachments") or []
        failed = [a for a in atts if not a.get("file_name")]
        if not failed:
            continue
        # 从详情解析 JSON 取原始 uuid
        detail = load_json(HTML_DIR / nid[:8] / f"{nid}.json", {})
        orig_atts = {a.get("url"): a for a in detail.get("attachments", [])}
        att_dir = ATTACH_DIR / nid
        att_dir.mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        session.headers.update(HEADERS)
        page_url = n.get("url", "")
        if page_url:
            try:
                session.get(page_url, headers={"Referer": "http://www.ccgp.gov.cn/"}, timeout=30)
            except Exception as exc:
                print(" 页面请求失败", nid, exc)
        any_fixed = False
        for a in failed:
            uuid = None
            orig = orig_atts.get(a.get("url")) or {}
            uuid = orig.get("uuid") or a.get("uuid")
            if not uuid:
                import urllib.parse
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(a.get("url", "")).query)
                uuid = (qs.get("uuid") or [""])[0]
            if not uuid:
                print(" SKIP(无uuid)", nid, a.get("source_name"))
                continue
            candidates = uuid_candidates(uuid)
            ok = False
            for cand in candidates:
                try:
                    r = session.get(cand, headers={"Referer": page_url}, timeout=90, allow_redirects=True)
                    if r.status_code == 200 and len(r.content) >= 16:
                        fname = safe_name(get_filename(r, a.get("source_name") or f"attachment.pdf"))
                        # 同名不同内容则加序号
                        p = att_dir / fname
                        stem, ext = (fname.rsplit(".", 1) + [""])[:2] if "." in fname else (fname, "")
                        k = 1
                        while p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() != hashlib.sha256(r.content).hexdigest():
                            p = att_dir / f"{stem}_{k}.{ext}" if ext else att_dir / f"{stem}_{k}"
                            k += 1
                        p.write_bytes(r.content)
                        a["file_name"] = p.name
                        a["bytes"] = len(r.content)
                        a["sha256"] = hashlib.sha256(r.content).hexdigest()
                        a["content_type"] = r.headers.get("Content-Type", "")
                        a["downloaded_url"] = cand
                        a.pop("error", None)
                        print(" FIXED", nid, fname, len(r.content))
                        fixed += 1
                        any_fixed = True
                        ok = True
                        break
                    else:
                        print(" CAND_FAIL", nid, cand, r.status_code)
                except Exception as exc:
                    print(" CAND_ERR", nid, cand, exc)
                time.sleep(1.0)
            if not ok:
                print(" STILL_FAIL", nid, a.get("source_name"))
        if any_fixed:
            ok_files = [a for a in atts if a.get("file_name")]
            ok_count = len(ok_files)
            total = len(atts)
            n["attachment_ok_count"] = ok_count
            n["attachment_total_count"] = total
            n["attachments_done"] = ok_count == total
            rebuild_zip_for_notice(nid, n)
            seen[nid] = n
            save_json(MANIFEST, manifest)
            save_json(STATE, seen)
    print("修复附件数", fixed)


def rebuild_zip_for_notice(nid, notice):
    att_dir = ATTACH_DIR / nid
    ok_files = [a for a in (notice.get("attachments") or []) if a.get("file_name")]
    if not ok_files:
        return
    # 同名去重：sha 相同只保留一个；sha 不同重命名
    seen_names = {}
    zip_items = []
    for a in ok_files:
        p = att_dir / a["file_name"]
        if not p.exists():
            continue
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        name = a["file_name"]
        key = name
        if key in seen_names:
            if seen_names[key] == sha:
                continue  # 完全相同，不重复打包
            stem, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
            k = 1
            while key in seen_names:
                key = f"{stem}_{k}.{ext}" if ext else f"{stem}_{k}"
                k += 1
        seen_names[key] = sha
        zip_items.append((key, p))
    manifest_file = {
        "notice_id": nid,
        "source_url": notice.get("url", ""),
        "files": [{**{k: v for k, v in a.items() if k != "error"}, "zip_name": key} for a, (key, _p) in
                  zip([a for a in ok_files], zip_items)],
        "ok_count": len(zip_items),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    zip_path = ATTACH_DIR / f"{nid}.zip"
    tmp = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for key, p in zip_items:
            zf.write(p, arcname=key)
        zf.writestr("_files_manifest.json", json.dumps(manifest_file, ensure_ascii=False, indent=2))
    tmp.replace(zip_path)
    notice["zip_file"] = str(zip_path.relative_to(ROOT))
    mirror = MIRROR_ATTACH / zip_path.name
    if mirror.exists():
        mirror.unlink()
    shutil.copy2(zip_path, mirror)
    print(" REZIP", nid, len(zip_items), "个唯一文件")


def dedupe_all_zips():
    manifest = load_json(MANIFEST, {"notices": {}})
    seen = load_json(STATE, {})
    for nid, n in manifest["notices"].items():
        if n.get("attachment_ok_count", 0) > 0:
            rebuild_zip_for_notice(nid, n)
            seen[nid] = n
    save_json(MANIFEST, manifest)
    save_json(STATE, seen)
    print("重打包完成")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--dedupe-zips", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.retry or args.all:
        retry_failed()
    if args.dedupe_zips or args.all:
        dedupe_all_zips()


if __name__ == "__main__":
    main()
