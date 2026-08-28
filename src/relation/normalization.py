"""Conservative organization normalization and deterministic IDs."""
from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_org_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,。；;：:、]", "", text)
    return text.casefold()


def stable_id(prefix: str, *parts: object, length: int = 20) -> str:
    raw = "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:length]}"
