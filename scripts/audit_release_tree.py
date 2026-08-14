#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.release_tree_audit import audit_git_tree, findings_as_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit tracked files for release-tree hygiene")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Git repository to audit")
    parser.add_argument("--format", choices=("json",), default="json", help="Output format")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        findings = audit_git_tree(args.root)
    except (OSError, RuntimeError) as exc:
        print(f"release-tree audit failed: {exc}", file=sys.stderr)
        return 2

    print(findings_as_json(findings))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
