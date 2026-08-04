"""统一平台启动入口（组合根）：python3 -m src.composition.serve --port 8400"""

from __future__ import annotations

import argparse

import uvicorn

from .build import build_app_with_bundle, build_production_bundle


def main() -> None:
    p = argparse.ArgumentParser(description="Unified Platform (8400)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8400)
    args = p.parse_args()

    bundle = build_production_bundle()
    app = build_app_with_bundle(bundle)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
