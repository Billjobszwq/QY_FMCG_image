#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


LEGACY_LINKS = {
    ".models": "recognition-models/registry",
    ".sam_checkpoints": "recognition-models/foundation/sam",
    ".datasets": "training-data/processed/datasets",
    ".datasets_nextgen": "training-data/processed/datasets-nextgen",
    ".training_data": "training-data/processed/training-data",
    ".batch3_clean": "training-data/processed/batch3-clean",
    ".kb": "training-data/processed/knowledge-base",
    ".micro_gold_v1": "training-data/evaluation/micro-gold-v1",
    ".micro_gold_v2": "training-data/evaluation/micro-gold-v2",
    ".data_protocol": "training-data/evaluation/data-protocol",
    ".eval": "training-data/evaluation/legacy-eval",
    ".platform": "runtime/platform",
    ".label-studio": "runtime/label-studio",
}


def _resolved_root(root: Path | str | None) -> Path:
    candidate = Path(__file__).resolve().parents[1] if root is None else Path(root)
    return candidate.expanduser().resolve()


def _ensure_real_directory(root: Path, relative_path: str, *, dry_run: bool) -> None:
    current = root
    for component in Path(relative_path).parts:
        current = current / component
        if current.is_symlink():
            raise OSError(f"target path must not contain a symlink: {relative_path}")
        if current.exists():
            if not current.is_dir():
                raise OSError(f"target path is not a directory: {relative_path}")
            continue
        if not dry_run:
            current.mkdir()


def _is_expected_relative_link(link_value: str, expected: str) -> bool:
    return not os.path.isabs(link_value) and os.path.normpath(link_value) == os.path.normpath(
        expected
    )


def _result(
    legacy_path: str, target_path: str, status: str, detail: str
) -> dict[str, str]:
    return {
        "legacy_path": legacy_path,
        "target_path": target_path,
        "status": status,
        "detail": detail,
    }


def bootstrap_local_assets(
    root: Path | str | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    project_root = _resolved_root(root)
    if not project_root.is_dir():
        raise OSError(f"project root is not a directory: {project_root}")

    target_was_missing = {
        target_path: not (project_root / target_path).exists()
        for target_path in LEGACY_LINKS.values()
    }
    for target_path in LEGACY_LINKS.values():
        _ensure_real_directory(project_root, target_path, dry_run=dry_run)

    results: list[dict[str, str]] = []
    for legacy_path, target_path in LEGACY_LINKS.items():
        legacy = project_root / legacy_path
        target = project_root / target_path
        relative_target = os.path.relpath(target, start=legacy.parent)

        if legacy.is_symlink():
            link_value = os.readlink(legacy)
            if _is_expected_relative_link(link_value, relative_target):
                results.append(
                    _result(
                        legacy_path,
                        target_path,
                        "unchanged",
                        "relative symlink already points to target",
                    )
                )
            else:
                results.append(
                    _result(
                        legacy_path,
                        target_path,
                        "conflict",
                        "legacy path is a symlink with a different target",
                    )
                )
            continue

        if legacy.exists():
            entity = "directory" if legacy.is_dir() else "file" if legacy.is_file() else "entity"
            results.append(
                _result(
                    legacy_path,
                    target_path,
                    "conflict",
                    f"legacy path is an existing {entity}",
                )
            )
            continue

        if dry_run:
            detail = (
                "would create target directory and relative symlink"
                if target_was_missing[target_path]
                else "would create relative symlink"
            )
            results.append(
                _result(
                    legacy_path,
                    target_path,
                    "created",
                    detail,
                )
            )
            continue

        try:
            legacy.symlink_to(relative_target, target_is_directory=True)
        except FileExistsError:
            results.append(
                _result(
                    legacy_path,
                    target_path,
                    "conflict",
                    "legacy path appeared before the symlink could be created",
                )
            )
        else:
            results.append(
                _result(
                    legacy_path,
                    target_path,
                    "created",
                    "created relative symlink",
                )
            )

    return {
        "ok": all(result["status"] != "conflict" for result in results),
        "root": str(project_root),
        "results": results,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create local asset directories and safe legacy compatibility links"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="project root (defaults to the repository containing this script)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report planned changes without modifying the filesystem",
    )
    return parser.parse_args(argv)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        root = _resolved_root(args.root)
        payload = bootstrap_local_assets(root, dry_run=args.dry_run)
    except (OSError, RuntimeError) as exc:
        try:
            root_text = str(_resolved_root(args.root))
        except (OSError, RuntimeError):
            root_text = str(args.root) if args.root is not None else str(Path(__file__).parent)
        _print_json({"ok": False, "root": root_text, "results": []})
        print(f"local asset bootstrap failed: {exc}", file=sys.stderr)
        return 2

    _print_json(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
