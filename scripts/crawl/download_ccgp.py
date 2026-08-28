# -*- coding: utf-8 -*-
"""
中国政府采购网（ccgp.gov.cn）中标/成交公告批量下载器

功能：
1. 抓取指定栏目列表页（静态分页 index.htm / index_1.htm ...）；
2. 下载公告原始 HTML（保留原始字节）；
3. 解析每个公告正文与附件信息，输出轻量 JSON；
4. 通过同 Session 下载附件并打包为 {notice_id}.zip；
5. 断点续抓：已成功的 notice_id 自动跳过，失败重试 3 次；
6. 所有元数据写入 dataset_build/manifests/manifest.json / manifest.csv。

示例：
    python scripts/crawl/download_ccgp.py --mode all --max-pages 3 --max-notices 150
    python scripts/crawl/download_ccgp.py --mode html
    python scripts/crawl/download_ccgp.py --mode attachments
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import random
import re
import shutil
import sys
import time
import urllib.parse
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import lxml.html
import requests

ROOT = Path(__file__).resolve().parents[2]
CRAWL_DIR = ROOT / "dataset_build" / "crawl"
HTML_DIR = CRAWL_DIR / "html"
ATTACH_DIR = CRAWL_DIR / "attachments"
LOG_DIR = CRAWL_DIR / "logs"
STATE_DIR = CRAWL_DIR / "state"
MANIFEST_DIR = ROOT / "dataset_build" / "manifests"
MIRROR_T1_NOTICES = ROOT / "dataset_build" / "mirror_task1" / "notices"
MIRROR_T1_ATTACH = ROOT / "dataset_build" / "mirror_task1" / "attachments"

for d in (HTML_DIR, ATTACH_DIR, LOG_DIR, STATE_DIR, MANIFEST_DIR, MIRROR_T1_NOTICES, MIRROR_T1_ATTACH):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 常见公告栏目：地方/中央 x 中标/成交
LIST_SOURCES = {
    "dfgg/zbgg": {"base": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/", "type": "地方中标公告"},
    "zygg/zbgg": {"base": "http://www.ccgp.gov.cn/cggg/zygg/zbgg/", "type": "中央中标公告"},
    "dfgg/cjgg": {"base": "http://www.ccgp.gov.cn/cggg/dfgg/cjgg/", "type": "地方成交公告"},
    "zygg/cjgg": {"base": "http://www.ccgp.gov.cn/cggg/zygg/cjgg/", "type": "中央成交公告"},
}

DETAIL_RE = re.compile(r"/(\d{6})/t(\d{8})_(\d+)\.htm$", re.I)
FILE_EXT_RE = re.compile(r"\.(docx?|xlsx?|pdf|zip|rar|7z|jpg|jpeg|png|gif|bmp|tiff?|txt|csv)(?:\?|$)", re.I)
INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t\x00-\x1f]+')


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with (LOG_DIR / "download_ccgp.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = INVALID_FILENAME_RE.sub("_", name).strip().strip(".")
    name = name or "attachment"
    if len(name) > max_len:
        stem, ext = name.rsplit(".", 1) if "." in name else (name, "")
        name = stem[: max_len - len(ext) - 1] + ("." + ext if ext else "")
    return name


def random_sleep(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def looks_like_block_page(text: str, content_len: int) -> bool:
    """识别反爬提示页/403 页面。"""
    if content_len < 4000 and ("访问过于频繁" in text or "频繁访问" in text or "稍后再试" in text):
        return True
    if "事件ID" in text and "您的IP地址" in text:
        return True
    return False


class SafeSession(requests.Session):
    """对 ccgp 的 403/反爬页面做统一退避重试。"""

    def __init__(self, retries: int = 3, backoff: float = 30.0):
        super().__init__()
        self.headers.update(DEFAULT_HEADERS)
        self.retries = retries
        self.backoff = backoff

    def get_text_or_bytes(self, url: str, *, referer: str = "http://www.ccgp.gov.cn/",
                          timeout: int = 60, raw: bool = False, retries: Optional[int] = None,
                          backoff: Optional[float] = None):
        max_retries = self.retries if retries is None else retries
        base_backoff = self.backoff if backoff is None else backoff
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                headers = {"Referer": referer}
                r = self.get(url, headers=headers, timeout=timeout, allow_redirects=True)
                if r.status_code in (403, 429, 503):
                    log(f"HTTP {r.status_code} @ {url}，退避 {base_backoff:.0f}s（第{attempt}次）")
                    if attempt < max_retries:
                        time.sleep(base_backoff * attempt + random.uniform(1, 5))
                    continue
                if not raw:
                    r.encoding = r.apparent_encoding or r.encoding or "utf-8"
                    text = r.text
                    if looks_like_block_page(text, len(r.content)):
                        log(f"反爬拦截页 @ {url}，退避 {base_backoff:.0f}s（第{attempt}次）")
                        if attempt < max_retries:
                            time.sleep(base_backoff * attempt + random.uniform(1, 5))
                        continue
                if raw and len(r.content) < 200:
                    log(f"内容过短（{len(r.content)}B）@ {url}，重试（第{attempt}次）")
                    if attempt < max_retries:
                        time.sleep(2 * attempt)
                    continue
                return r
            except requests.RequestException as exc:
                last_exc = exc
                log(f"请求异常 @ {url}: {exc}，重试（第{attempt}次）")
                time.sleep(3 * attempt + random.uniform(1, 3))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"下载失败（重试后仍失败）: {url}")


def get_list_page(session: SafeSession, source_key: str, page_index: int) -> Optional[Tuple[str, str]]:
    """
    抓取栏目列表页。返回 (url, html_text)。
    page_index: 0 -> index.htm；1 -> index_1.htm；...
    """
    base = LIST_SOURCES[source_key]["base"]
    if page_index == 0:
        url = base + "index.htm"
    else:
        url = base + f"index_{page_index}.htm"
    r = session.get_text_or_bytes(url, referer="http://www.ccgp.gov.cn/", timeout=60)
    return r.url, r.text


def parse_list_page(url: str, html_text: str, source_key: str) -> List[dict]:
    """从列表页抽取公告条目。"""
    root = lxml.html.fromstring(html_text)
    results: List[dict] = []
    seen_href: set[str] = set()

    for li in root.xpath("//ul[contains(concat(' ', normalize-space(@class), ' '), ' c_list_bid ')]/li"):
        anchors = li.xpath(".//a[@href]")
        if not anchors:
            continue
        a = anchors[0]
        href = a.get("href") or ""
        if not DETAIL_RE.search(href):
            # 详情链接可能是相对路径 ./YYYYMM/t...htm
            norm = urllib.parse.urljoin(url, href)
            if not DETAIL_RE.search(norm):
                continue
            href = norm
        else:
            href = urllib.parse.urljoin(url, href)
        m = DETAIL_RE.search(href)
        if not m or href in seen_href:
            continue
        if "/cggg/" not in href:
            # 只保留政采公告栏目，排除右侧新闻/法规等边栏
            continue
        seen_href.add(href)
        notice_id = f"{m.group(2)}_{m.group(3)}"
        text = " ".join(li.text_content().split())
        item = {
            "notice_id": notice_id,
            "url": href,
            "source_key": source_key,
            "source_type": LIST_SOURCES[source_key]["type"],
            "title": " ".join(a.text_content().split()),
            "raw_text": text,
            "publish_time": extract_field(text, r"发布时间[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})"),
            "region": extract_field(text, r"地域[:：]\s*([^\s]+)"),
            "buyer": extract_field(text, r"采购人[:：]\s*([^\s]+)"),
        }
        results.append(item)
    return results


def extract_field(text: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def uuid_download_urls(uuid: str) -> List[str]:
    """生成 uuid 附件下载候选 URL。

    实测规律：
    - 带连字符的 36 位 uuid：http://download.ccgp.gov.cn 可用，https 返回 403；
    - 不带连字符的 32 位 uuid：https://download.ccgp.gov.cn 可用，http 返回 403。
    """
    compact = re.sub(r"[^0-9a-fA-F]", "", uuid)
    variants: List[str] = []
    if compact:
        variants.append(compact)
        if len(compact) == 32:
            variants.append("-".join([compact[0:8], compact[8:12], compact[12:16], compact[16:20], compact[20:32]]))
    if uuid and uuid not in variants:
        variants.append(uuid)
    if "-" in (uuid or ""):
        schemes = ["http", "https"]
    else:
        schemes = ["https", "http"]
    urls: List[str] = []
    for scheme in schemes:
        for vid in variants:
            u = f"{scheme}://download.ccgp.gov.cn/oss/download?uuid={vid}"
            if u not in urls:
                urls.append(u)
    return urls


def parse_detail(html_bytes: bytes, page_url: str) -> dict:
    """解析详情页：标题、正文文本、附件。"""
    root = lxml.html.fromstring(html_bytes)
    doc = root.getroottree()

    title = None
    for xp in (
        ".//div[contains(@class,'vF_detail_header')]//h2",
        ".//div[contains(@class,'vF_detail')]//h1",
        ".//h1",
        ".//h2",
        ".//title",
    ):
        nodes = root.xpath(xp)
        if nodes:
            title = " ".join(nodes[0].text_content().split())
            if title:
                break

    # 页面正文文本
    content_text = ""
    for cls in ("vF_detail_content", "vT_detail_content", "vF_detail"):
        nodes = root.xpath(f".//div[contains(@class,'{cls}')]")
        if nodes:
            content_text = " ".join(nodes[0].text_content().split())
            if content_text:
                break
    if not content_text:
        body = root.find(".//body")
        content_text = " ".join(body.text_content().split()) if body is not None else ""

    # 元信息表格（公告概要）
    meta = {}
    for table in root.xpath(".//div[contains(@class,'vF_detail')]//table[.//td]"):
        rows = table.xpath(".//tr")
        if len(rows) > 8:
            continue
        for tr in rows:
            tds = tr.xpath("./td")
            if len(tds) >= 2:
                k = " ".join(tds[0].text_content().split()).rstrip("：:")
                v = " ".join(tds[1].text_content().split())
                if k and v and 2 <= len(k) <= 20:
                    meta[k] = v
        if meta:
            break

    # 附件：新版 a.bizDownload（id 为 uuid），也兼容传统文件链接
    attachments: List[dict] = []
    for a in root.xpath("//a[contains(@class,'bizDownload')]"):
        uuid = (a.get("id") or "").strip()
        name = " ".join(a.text_content().split())
        if uuid and uuid not in ("", "null"):
            urls = uuid_download_urls(uuid)
            attachments.append({
                "name": name,
                "uuid": uuid,
                "url": urls[0],
                "alt_urls": urls[1:],
                "kind": "bizDownload",
            })
    for a in root.xpath("//a[@href]"):
        href = a.get("href") or ""
        low = href.lower()
        if low.startswith(("javascript", "#", "mailto")):
            continue
        if "/oss/download" in low:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            uuid = (qs.get("uuid", [""])[0] or "").strip()
            name = " ".join(a.text_content().split()) or Path(urllib.parse.urlparse(href).path).name
            urls = uuid_download_urls(uuid) if uuid else []
            attachments.append({
                "name": name,
                "uuid": uuid or None,
                "url": urls[0] if urls else urllib.parse.urljoin(page_url, href),
                "alt_urls": urls[1:] if urls else [],
                "kind": "oss_direct",
            })
            continue
        if FILE_EXT_RE.search(low) and "/cggg/" not in low:
            name = " ".join(a.text_content().split()) or Path(urllib.parse.urlparse(href).path).name
            attachments.append({
                "name": name,
                "uuid": None,
                "url": urllib.parse.urljoin(page_url, href),
                "alt_urls": [],
                "kind": "direct",
            })

    # 去重（按 url）
    unique: Dict[str, dict] = {}
    for att in attachments:
        unique[att["url"]] = att
    return {
        "url": page_url,
        "title": title,
        "meta": meta,
        "content_text": content_text[:200000],
        "attachments": list(unique.values()),
    }


def parse_content_disposition(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = re.search(r"filename\*?=(?:UTF-8''|utf-8''|['\"]?)([^;'\"]+)", value, re.I)
    if m:
        return urllib.parse.unquote(m.group(1))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.I)
    return urllib.parse.unquote(m.group(1)) if m else None


def guess_extension(headers: dict, url: str, name: str) -> str:
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext = None
    if ctype == "application/pdf":
        ext = ".pdf"
    elif ctype in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"):
        ext = ".docx"
    elif ctype in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"):
        ext = ".xlsx"
    elif ctype.startswith("image/"):
        ext = mimetypes.guess_extension(ctype) or ".img"
    if not ext:
        m = FILE_EXT_RE.search(url)
        if m:
            ext = "." + m.group(1).lower()
    if not ext and "." in name:
        ext = "." + name.rsplit(".", 1)[1]
    return ext or ".bin"


def download_attachment(session: SafeSession, att: dict, out_dir: Path, referer: str, idx: int) -> dict:
    """下载单个附件（自动尝试替代 uuid 写法），返回本地文件信息。"""
    candidates = [att["url"]] + [u for u in (att.get("alt_urls") or []) if u != att["url"]]
    raw = None
    errors = []
    for cand in candidates:
        try:
            raw = session.get_text_or_bytes(cand, referer=referer, timeout=180, raw=True, retries=2, backoff=10.0)
            break
        except Exception as exc:
            errors.append(f"{cand}: {exc}")
    if raw is None or raw.status_code != 200 or len(raw.content) < 16:
        raise RuntimeError(" / ".join(errors or [f"HTTP {raw.status_code if raw is not None else 'N/A'}"]))
    cd_name = parse_content_disposition(raw.headers.get("Content-Disposition"))
    ext = guess_extension(raw.headers, att["url"], cd_name or att["name"] or "")
    base = sanitize_filename(cd_name or att["name"] or f"attachment_{idx}")
    if not base.lower().endswith(ext.lower()):
        base += ext
    # 同名冲突追加序号
    path = out_dir / base
    n = 1
    stem = Path(base).stem
    while path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(raw.content).hexdigest():
        path = out_dir / f"{stem}_{n}{ext}"
        n += 1
    path.write_bytes(raw.content)
    return {
        "file_name": path.name,
        "relative_path": f"attachments/{out_dir.name}/{path.name}",
        "bytes": len(raw.content),
        "sha256": hashlib.sha256(raw.content).hexdigest(),
        "content_type": (raw.headers.get("Content-Type") or "").split(";")[0],
        "url": att["url"],
        "source_name": att["name"],
    }


def make_zip(notice_id: str, files: List[dict], files_manifest: dict) -> Path:
    zip_path = ATTACH_DIR / f"{notice_id}.zip"
    tmp = zip_path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            p = ATTACH_DIR / notice_id / f["file_name"]
            if p.exists():
                zf.write(p, arcname=f["file_name"])
        zf.writestr("_files_manifest.json", json.dumps(files_manifest, ensure_ascii=False, indent=2))
    tmp.replace(zip_path)
    return zip_path


def load_state(name: str) -> dict:
    p = STATE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(name: str, data: dict) -> None:
    tmp = STATE_DIR / (name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_DIR / name)


def load_manifest() -> dict:
    p = MANIFEST_DIR / "manifest.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "notices": {}}


def save_manifest(manifest: dict) -> None:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_DIR / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_DIR / "manifest.json")
    # 同时生成 csv 便于查看
    with (MANIFEST_DIR / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["notice_id", "title", "url", "source_type", "publish_time", "region", "buyer",
                    "html_file", "zip_file", "attachment_count", "status"])
        for nid, n in manifest["notices"].items():
            atts = n.get("attachments") or []
            w.writerow([nid, n.get("title", ""), n.get("url", ""), n.get("source_type", ""),
                        n.get("publish_time", ""), n.get("region", ""), n.get("buyer", ""),
                        n.get("html_file", ""), n.get("zip_file", ""), len(atts), n.get("status", "")])


def mirror_to_task1(notice: dict) -> None:
    """把已抓取公告镜像成官方任务一目录结构：一篇公告一个 zip，公告为 html 文件。"""
    html_src = Path(notice["html_file"]) if notice.get("html_file") else None
    zip_src = Path(notice["zip_file"]) if notice.get("zip_file") else None
    if html_src and html_src.exists():
        dst = MIRROR_T1_NOTICES / html_src.name
        if not dst.exists():
            shutil.copy2(html_src, dst)
    if zip_src and zip_src.exists():
        dst = MIRROR_T1_ATTACH / zip_src.name
        if not dst.exists():
            shutil.copy2(zip_src, dst)


def attachment_ext_counts(manifest: dict) -> Counter:
    """统计已成功下载附件的扩展名分布。"""
    c: Counter = Counter()
    for n in manifest.get("notices", {}).values():
        for a in (n.get("attachments") or []):
            fname = a.get("file_name")
            if fname:
                c[Path(fname).suffix.lower()] += 1
    return c


def targets_met(counts: Counter, target_exts: List[str], target_min: int) -> bool:
    exts = [e.lower() if e.startswith(".") else "." + e.lower() for e in target_exts]
    return all(counts.get(e, 0) >= target_min for e in exts)


def collect_notices(args) -> List[dict]:
    """根据栏目与页数收集详情 URL 清单（不做下载）。"""
    session = SafeSession(retries=args.retries, backoff=args.backoff)
    notices: List[dict] = []
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    for source in sources:
        if source not in LIST_SOURCES:
            log(f"未知栏目 {source}，跳过")
            continue
        for page in range(args.max_pages):
            try:
                url, text = get_list_page(session, source, page)
                items = parse_list_page(url, text, source)
                log(f"[列表] {source} 第{page + 1}页 -> {len(items)} 条")
                notices.extend(items)
            except Exception as exc:
                log(f"[列表] {source} 第{page + 1}页失败: {exc}")
            random_sleep(args.list_delay_min, args.list_delay_max)
    # 按 notice_id 去重（保留先出现），并排除非政采公告栏目链接
    uniq: Dict[str, dict] = {}
    for n in notices:
        if "/cggg/" in n.get("url", ""):
            uniq.setdefault(n["notice_id"], n)
    notices = list(uniq.values())
    if args.max_notices:
        notices = notices[: args.max_notices]
    log(f"共收集 {len(notices)} 条唯一公告")
    return notices


def process_notice(session: SafeSession, item: dict, args, manifest: dict,
                   seen: Dict[str, dict], failed: Dict[str, dict]) -> bool:
    nid = item["notice_id"]
    date_dir = HTML_DIR / nid[:8]
    date_dir.mkdir(parents=True, exist_ok=True)
    html_path = date_dir / f"{nid}.html"
    json_path = date_dir / f"{nid}.json"

    entry = seen.get(nid, {})
    html_ok = entry.get("html_ok") if not args.force else False

    try:
        # 1) 详情页
        if not html_ok:
            r = session.get_text_or_bytes(item["url"], referer="http://www.ccgp.gov.cn/", timeout=60)
            raw = r.content
            if len(raw) < 3000 and b"\xe8\xae\xbf\xe9\x97\xae" in raw:
                # 反爬页面：重试一次
                random_sleep(20, 40)
                r = session.get_text_or_bytes(item["url"], referer="http://www.ccgp.gov.cn/", timeout=60)
                raw = r.content
            html_path.write_bytes(raw)
            parsed = parse_detail(raw, item["url"])
            json_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
            item["title"] = item["title"] or parsed["title"]
            item["detail_parsed"] = parsed
            entry.update({
                "url": item["url"],
                "title": item["title"],
                "source_key": item.get("source_key"),
                "source_type": item.get("source_type"),
                "publish_time": item.get("publish_time"),
                "region": item.get("region"),
                "buyer": item.get("buyer"),
                "html_file": str(html_path.relative_to(ROOT)),
                "json_file": str(json_path.relative_to(ROOT)),
                "html_ok": True,
                "attachments": [],
                "status": "html_ok",
            })
            log(f"[HTML] {nid} {item['title'][:60]}")
        else:
            item["detail_parsed"] = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}

        attachments_meta = item.get("detail_parsed", {}).get("attachments", [])

        # 2) 附件
        if args.mode in ("attachments", "all") and attachments_meta:
            att_dir = ATTACH_DIR / nid
            att_dir.mkdir(parents=True, exist_ok=True)
            files: List[dict] = []
            for idx, att in enumerate(attachments_meta, 1):
                rnd = random.uniform(args.att_delay_min, args.att_delay_max)
                time.sleep(rnd)
                try:
                    info = download_attachment(session, att, att_dir, item["url"], idx)
                    files.append(info)
                    log(f"[ATT] {nid} <- {info['file_name']} ({info['bytes']}B)")
                except Exception as exc:
                    log(f"[ATT] {nid} 附件失败 {att.get('name')}: {exc}")
                    files.append({
                        "file_name": None,
                        "url": att["url"],
                        "source_name": att.get("name"),
                        "error": str(exc),
                    })
            ok_files = [f for f in files if f.get("file_name")]
            files_manifest = {
                "notice_id": nid,
                "source_url": item["url"],
                "files": files,
                "ok_count": len(ok_files),
                "total_count": len(files),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            if ok_files:
                zip_path = make_zip(nid, ok_files, files_manifest)
                entry["zip_file"] = str(zip_path.relative_to(ROOT))
                entry["attachments"] = files
                entry["attachment_ok_count"] = len(ok_files)
                entry["attachment_total_count"] = len(files)
                entry["attachments_done"] = (len(ok_files) == len(files))
                log(f"[ZIP] {nid} -> {zip_path.name}（{len(ok_files)}/{len(files)} 个文件）")
            else:
                entry["attachments"] = files
                entry["attachment_ok_count"] = 0
                entry["attachment_total_count"] = len(files)
                entry["attachments_done"] = False
            entry["files_manifest"] = files_manifest
        elif args.mode in ("attachments", "all") and not attachments_meta:
            log(f"[ATT] {nid} 无附件")
            entry["attachments"] = []
            entry["attachment_ok_count"] = 0
            entry["attachment_total_count"] = 0
            entry["attachments_done"] = True

        entry["status"] = "ok"
        seen[nid] = entry
        manifest["notices"][nid] = entry
        mirror_to_task1(entry)
        failed.pop(nid, None)
        save_state("seen.json", seen)
        save_state("failed.json", failed)
        save_manifest(manifest)
        return True
    except Exception as exc:
        log(f"[FAIL] {nid}: {exc}")
        entry["status"] = "failed"
        entry["last_error"] = str(exc)
        failed[nid] = entry
        seen[nid] = entry
        save_state("seen.json", seen)
        save_state("failed.json", failed)
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["list", "html", "attachments", "all"], default="all")
    ap.add_argument("--sources", default="dfgg/zbgg,zygg/zbgg,dfgg/cjgg,zygg/cjgg")
    ap.add_argument("--max-pages", type=int, default=3, help="每个栏目抓取的列表页数")
    ap.add_argument("--max-notices", type=int, default=150, help="最多处理的公告数（0 表示不限制）")
    ap.add_argument("--list-delay-min", type=float, default=3.0)
    ap.add_argument("--list-delay-max", type=float, default=5.0)
    ap.add_argument("--att-delay-min", type=float, default=0.8)
    ap.add_argument("--att-delay-max", type=float, default=1.6)
    ap.add_argument("--backoff", type=float, default=30.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="忽略已成功状态，重新下载")
    ap.add_argument("--skip-incomplete", action="store_true", help="跳过此前附件未下全的公告，不再反复重试")
    ap.add_argument("--target-ext", default="", help="目标附件扩展名（逗号分隔，如 xls,xlsx,rar,jpg）")
    ap.add_argument("--target-min", type=int, default=5, help="每个目标扩展名至少达到的数量，达到后提前结束")
    args = ap.parse_args()

    target_exts = [s.strip() for s in (args.target_ext or "").split(",") if s.strip()]
    manifest = load_manifest()
    seen = load_state("seen.json")
    failed = load_state("failed.json")
    log(f"模式={args.mode} 栏目={args.sources} 列表页/栏目={args.max_pages} 上限={args.max_notices} "
        f"目标扩展名={target_exts or '无'}×{args.target_min}")

    notices = collect_notices(args)
    if args.mode == "list":
        print(json.dumps(notices, ensure_ascii=False, indent=2))
        return

    session = SafeSession(retries=args.retries, backoff=args.backoff)
    ok_count = 0
    fail_count = 0
    skip_count = 0
    for i, item in enumerate(notices, 1):
        nid = item["notice_id"]
        prev = seen.get(nid, {})
        att_total = int(prev.get("attachment_total_count", 0) or 0)
        att_ok = int(prev.get("attachment_ok_count", 0) or 0)
        att_incomplete = (att_ok < att_total)
        att_done = bool(prev.get("attachments_done")) or (att_total == 0 and att_ok == 0 and prev.get("html_ok"))
        html_done = bool(prev.get("html_ok"))
        if not args.force and prev.get("status") == "ok" and html_done:
            if args.mode == "html" and html_done:
                skip_count += 1
                log(f"[SKIP] {i}/{len(notices)} {nid} HTML 已完成")
                continue
            if args.mode in ("attachments", "all") and att_incomplete and args.skip_incomplete:
                skip_count += 1
                log(f"[SKIP] {i}/{len(notices)} {nid} 附件永久不完整，按参数跳过")
                continue
            if args.mode in ("attachments", "all") and (att_done or (att_total > 0 and att_ok == att_total)) and not att_incomplete:
                skip_count += 1
                log(f"[SKIP] {i}/{len(notices)} {nid} 已完成")
                continue
        log(f"[START] {i}/{len(notices)} {nid} {item['title'][:60]}")
        ok = process_notice(session, item, args, manifest, seen, failed)
        ok_count += int(ok)
        fail_count += int(not ok)
        if target_exts:
            counts = attachment_ext_counts(manifest)
            log(f"[EXT] {dict(sorted(counts.items()))}")
            if targets_met(counts, target_exts, args.target_min):
                log(f"[EXT] 目标扩展名均已达到 {args.target_min} 个，提前结束")
                break
        # 详情页与附件之间的主延迟
        delay = random.uniform(1.5, 3.0)
        time.sleep(delay)

    log(f"完成：成功 {ok_count}，失败 {fail_count}，跳过 {skip_count}")
    log(f"累计入库 {len(manifest['notices'])} 条，HTML {sum(1 for n in manifest['notices'].values() if n.get('html_ok'))}，"
        f"ZIP {sum(1 for n in manifest['notices'].values() if n.get('zip_file'))}")
    log(f"清单：{MANIFEST_DIR / 'manifest.json'}")
    log(f"HTML：{HTML_DIR}")
    log(f"附件：{ATTACH_DIR}")


if __name__ == "__main__":
    main()
