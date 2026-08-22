#!/usr/bin/env python3
"""模型管理浏览器验收专用 QA 服务器（M9）。

纪律：
- 绝不使用 live DB：从 live 只读复制一份到独立目录（可 --fresh 全新），
  副本上应用迁移；
- 凭据：QA 会话口令经命令行传入；模型 KEK 进程内随机生成（不落盘）；
- 只监听 127.0.0.1；验收结束即停。
"""
from __future__ import annotations

import argparse
import os
import secrets
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))  # noqa: 仅兼容，实际走包路径


def make_qa_db(dest: Path, *, fresh: bool) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    db = dest / "platform.sqlite"
    if fresh:
        return db  # PlatformStore 全新建库
    live = REPO_ROOT / "runtime" / "platform" / "platform.sqlite"
    src = sqlite3.connect(live.resolve().as_uri() + "?mode=ro", uri=True)
    tgt = sqlite3.connect(str(db))
    try:
        src.backup(tgt)
    finally:
        tgt.close()
        src.close()
    return db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp/taas-mm-qa")
    ap.add_argument("--port", type=int, default=8400)
    ap.add_argument("--fresh", action="store_true",
                    help="全新空库（不复制 live）")
    args = ap.parse_args()

    root = Path(args.root)
    db = make_qa_db(root, fresh=args.fresh)

    # KEK：进程内随机，仅经环境变量语义注入组合根（不落盘、不回显）
    import base64
    os.environ["TAAS_MODEL_SECRET_KEK"] = base64.b64encode(
        secrets.token_bytes(32)).decode()
    os.environ.setdefault("PLATFORM_USERS",
                          "admin:qa-admin-pw:admin,"
                          "checker:qa-checker-pw:admin,"
                          "emp:qa-emp-pw:operator")

    from src.composition.build import build_production_bundle
    from src.platform.api.app import create_app
    bundle = build_production_bundle(
        db_path=db, cas_root=root / "cas",
        recognition_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=None)

    import uvicorn
    print(f"[qa] db={db} port={args.port} fresh={args.fresh}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
