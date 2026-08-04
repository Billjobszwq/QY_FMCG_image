"""统一平台 8400 启动入口：python -m src.platform.api.run [--port 8400]"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


def build_app():
    return create_app(web_dist=REPO_ROOT / "web" / "dist")


app = build_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified Platform API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8400)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
