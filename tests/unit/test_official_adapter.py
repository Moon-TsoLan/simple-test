from __future__ import annotations

import zipfile
from pathlib import Path

from scripts.adapt.official_adapter import adapt_official_dataset, collect_pairs, detect_layout
from scripts.crawl.packaging import accept_list_item, interleave_by_source, pair_is_usable, sha256_file


def _html(title: str) -> bytes:
    return (
        "<html><head><title>x</title></head><body>"
        f"<div class='vF_detail_header'><h2>{title}</h2></div>"
        "<p>中标公告正文</p></body></html>"
    ).encode("utf-8")


def _zip_with_file(path: Path, name: str = "a.pdf", payload: bytes = b"%PDF-1.4 demo") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, payload)
        archive.writestr("_files_manifest.json", "{}")


def test_accept_list_item_filters_non_result_and_excluded_titles() -> None:
    ok, reason = accept_list_item({
        "source_key": "dfgg/zbgg",
        "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202609/t20260917_1.htm",
        "title": "某单位设备采购中标公告",
    })
    assert ok and reason == "ok"
    rejected, why = accept_list_item({
        "source_key": "dfgg/zbgg",
        "url": "http://www.ccgp.gov.cn/cggg/dfgg/zbgg/202609/t20260917_1.htm",
        "title": "某项目废标公告",
    })
    assert not rejected and why == "excluded_title"


def test_interleave_by_source_round_robins() -> None:
    items = [
        {"notice_id": "a", "source_key": "dfgg/zbgg"},
        {"notice_id": "b", "source_key": "dfgg/zbgg"},
        {"notice_id": "c", "source_key": "zygg/cjgg"},
    ]
    ordered = interleave_by_source(items)
    assert [item["notice_id"] for item in ordered] == ["a", "c", "b"]


def test_pair_is_usable_requires_real_zip_member(tmp_path: Path) -> None:
    html = tmp_path / "n.html"
    html.write_bytes(_html("实验室设备中标公告"))
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("_files_manifest.json", "{}")
    ok, reason, _ = pair_is_usable(html, empty)
    assert not ok and reason == "zip_no_real_files"
    good = tmp_path / "good.zip"
    _zip_with_file(good)
    ok, reason, meta = pair_is_usable(html, good)
    assert ok and reason == "ok"
    assert meta["attachment_names"] == ["a.pdf"]
    assert sha256_file(html) == meta["html_sha256"]


def test_adapter_split_dir_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "pack"
    notices = source / "notices"
    attachments = source / "attachments"
    notices.mkdir(parents=True)
    attachments.mkdir()
    (notices / "20260917_1.html").write_bytes(_html("中央单位成交公告"))
    _zip_with_file(attachments / "20260917_1.zip", "result.xlsx", b"PK\x03\x04fake")
    assert detect_layout(source) == "split_dir"
    output = tmp_path / "out"
    report = adapt_official_dataset(source, output, layout="auto")
    assert report["copied"] == 1
    dst_html = output / "notices" / "20260917_1.html"
    dst_zip = output / "attachments" / "20260917_1.zip"
    assert dst_html.is_file() and dst_zip.is_file()
    assert sha256_file(dst_html) == sha256_file(notices / "20260917_1.html")
    assert sha256_file(dst_zip) == sha256_file(attachments / "20260917_1.zip")


def test_adapter_per_folder_and_paired(tmp_path: Path) -> None:
    folders = tmp_path / "folders"
    one = folders / "N-88"
    one.mkdir(parents=True)
    (one / "page.htm").write_bytes(_html("地方中标公告"))
    _zip_with_file(one / "files.zip")
    assert detect_layout(folders) == "per_folder"
    pairs = collect_pairs(folders, "per_folder")
    assert pairs[0].notice_id == "N-88"

    paired = tmp_path / "paired"
    paired.mkdir()
    (paired / "abc.html").write_bytes(_html("成交公告"))
    _zip_with_file(paired / "abc.zip")
    assert detect_layout(paired) == "paired"
    out = tmp_path / "adapted"
    report = adapt_official_dataset(paired, out, layout="paired")
    assert report["copied"] == 1
    assert (out / "notices" / "abc.html").is_file()
