# -*- coding: utf-8 -*-
"""Run the local FastAPI + built Vue single-port application."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from src.api.app import DEFAULT_BLOCK_DIR, DEFAULT_DB, DEFAULT_UPLOAD, create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--block-dir", type=Path, default=DEFAULT_BLOCK_DIR)
    parser.add_argument("--upload-dir", type=Path, default=DEFAULT_UPLOAD)
    parser.add_argument("--frontend-dist", type=Path, default=ROOT / "frontend" / "dist")
    args = parser.parse_args()
    if args.reload:
        os.environ["APP_DB_PATH"] = str(args.db)
        os.environ["APP_BLOCK_DIR"] = str(args.block_dir)
        uvicorn.run("src.api.app:app", host=args.host, port=args.port, reload=True)
    else:
        app = create_app(
            args.db, frontend_dist=args.frontend_dist,
            upload_dir=args.upload_dir, block_dir=args.block_dir,
        )
        uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__": raise SystemExit(main())
