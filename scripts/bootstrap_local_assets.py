#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
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


class InvalidProjectRootError(RuntimeError):
    """Raised when --root is not recognizably this project's repository root."""


class RaceLostError(RuntimeError):
    """Raised when a competing filesystem entry disappears during commit."""


def _resolved_root(root: Path | str | None) -> Path:
    candidate = Path(__file__).resolve().parents[1] if root is None else Path(root)
    return candidate.expanduser().resolve()


def _path_kind(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "filesystem entity"


def _validate_project_root(root: Path) -> None:
    if _path_kind(root) != "directory":
        raise InvalidProjectRootError(f"project root is not a directory: {root}")

    sentinel_kinds = {
        ".git": {"directory", "file"},
        "pyproject.toml": {"file"},
        "src": {"directory"},
        "scripts": {"directory"},
    }
    invalid = [
        sentinel
        for sentinel, allowed_kinds in sentinel_kinds.items()
        if _path_kind(root / sentinel) not in allowed_kinds
    ]
    if invalid:
        names = ", ".join(invalid)
        raise InvalidProjectRootError(f"project root is missing safe repository sentinels: {names}")


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


def _error(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def _payload(
    root: Path | str,
    *,
    dry_run: bool,
    results: list[dict[str, str]],
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": error is None
        and all(result["status"] not in {"conflict", "error"} for result in results),
        "root": str(root),
        "dry_run": dry_run,
        "results": results,
        "error": error,
    }


def _target_conflict(root: Path, target_path: str) -> str | None:
    current = root
    for component in Path(target_path).parts:
        current = current / component
        kind = _path_kind(current)
        if kind == "missing":
            return None
        if kind != "directory":
            relative = current.relative_to(root).as_posix()
            return f"target component {relative} is an existing {kind}"
    return None


def _inspect_legacy(
    root: Path, legacy_path: str, target_path: str, target_conflict: str | None
) -> dict[str, str]:
    if target_conflict is not None:
        return _result(legacy_path, target_path, "conflict", target_conflict)

    legacy = root / legacy_path
    target = root / target_path
    kind = _path_kind(legacy)
    if kind == "missing":
        return _result(
            legacy_path,
            target_path,
            "would_create",
            "target directory and relative symlink would be created",
        )
    if kind == "symlink":
        link_value = os.readlink(legacy)
        relative_target = os.path.relpath(target, start=legacy.parent)
        if not _is_expected_relative_link(link_value, relative_target):
            return _result(
                legacy_path,
                target_path,
                "conflict",
                "legacy path is a symlink with a different target",
            )
        if _path_kind(target) != "directory":
            return _result(
                legacy_path,
                target_path,
                "conflict",
                "legacy path is a broken symlink",
            )
        return _result(
            legacy_path,
            target_path,
            "unchanged",
            "relative symlink already points to target",
        )
    return _result(
        legacy_path,
        target_path,
        "conflict",
        f"legacy path is an existing {kind}",
    )


def _preflight(root: Path) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for legacy_path, target_path in LEGACY_LINKS.items():
        target_conflict = _target_conflict(root, target_path)
        results.append(_inspect_legacy(root, legacy_path, target_path, target_conflict))
    return results


def _ensure_target_directory(root: Path, target_path: str) -> tuple[str, str] | None:
    current = root
    for component in Path(target_path).parts:
        current = current / component
        kind = _path_kind(current)
        if kind == "directory":
            continue
        if kind != "missing":
            relative = current.relative_to(root).as_posix()
            return "conflict", f"target component {relative} appeared as an existing {kind}"

        # Recheck immediately before mkdir to narrow the race window.
        kind = _path_kind(current)
        if kind == "directory":
            continue
        if kind != "missing":
            relative = current.relative_to(root).as_posix()
            return "conflict", f"target component {relative} appeared as an existing {kind}"
        try:
            current.mkdir()
        except FileExistsError:
            kind = _path_kind(current)
            if kind == "directory":
                continue
            relative = current.relative_to(root).as_posix()
            return "conflict", f"target component {relative} appeared as an existing {kind}"

        kind = _path_kind(current)
        if kind != "directory":
            relative = current.relative_to(root).as_posix()
            return "conflict", f"target component {relative} is no longer a directory"
    return None


def _operation_error_result(
    legacy_path: str, target_path: str, exc: BaseException
) -> dict[str, str]:
    return _result(
        legacy_path,
        target_path,
        "error",
        f"operation failed with {type(exc).__name__}",
    )


def _mutate(root: Path, plan: list[dict[str, str]], *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return _payload(root, dry_run=True, results=plan)

    journal: list[dict[str, str]] = []
    for planned in plan:
        legacy_path = planned["legacy_path"]
        target_path = planned["target_path"]

        try:
            precommit_target_conflict = _target_conflict(root, target_path)
            precommit = _inspect_legacy(
                root, legacy_path, target_path, precommit_target_conflict
            )
        except (OSError, RuntimeError) as exc:
            journal.append(_operation_error_result(legacy_path, target_path, exc))
            return _payload(
                root,
                dry_run=False,
                results=journal,
                error=_error(exc),
            )
        if precommit["status"] == "unchanged":
            journal.append(precommit)
            continue
        if precommit["status"] == "conflict":
            journal.append(precommit)
            return _payload(root, dry_run=False, results=journal)
        if planned["status"] == "unchanged":
            exc = RaceLostError(
                f"unchanged legacy path disappeared before commit: {legacy_path}"
            )
            journal.append(_operation_error_result(legacy_path, target_path, exc))
            return _payload(
                root,
                dry_run=False,
                results=journal,
                error=_error(exc),
            )

        try:
            target_conflict = _ensure_target_directory(root, target_path)
        except (OSError, RuntimeError) as exc:
            journal.append(_operation_error_result(legacy_path, target_path, exc))
            return _payload(
                root,
                dry_run=False,
                results=journal,
                error=_error(exc),
            )
        if target_conflict is not None:
            _, detail = target_conflict
            journal.append(_result(legacy_path, target_path, "conflict", detail))
            return _payload(root, dry_run=False, results=journal)

        try:
            # Recheck both sides immediately before creating the compatibility
            # link. A concurrent writer may have replaced the target after mkdir.
            target_conflict = _target_conflict(root, target_path)
            current = _inspect_legacy(
                root, legacy_path, target_path, target_conflict
            )
        except (OSError, RuntimeError) as exc:
            journal.append(_operation_error_result(legacy_path, target_path, exc))
            return _payload(
                root,
                dry_run=False,
                results=journal,
                error=_error(exc),
            )
        if current["status"] == "unchanged":
            journal.append(current)
            continue
        if current["status"] == "conflict":
            journal.append(current)
            return _payload(root, dry_run=False, results=journal)

        legacy = root / legacy_path
        target = root / target_path
        relative_target = os.path.relpath(target, start=legacy.parent)
        try:
            # _inspect_legacy is the immediate pre-symlink recheck. FileExistsError
            # is re-inspected because another process may win after that check.
            legacy.symlink_to(relative_target, target_is_directory=True)
        except FileExistsError:
            try:
                raced_target_conflict = _target_conflict(root, target_path)
                raced = _inspect_legacy(
                    root, legacy_path, target_path, raced_target_conflict
                )
            except (OSError, RuntimeError) as exc:
                journal.append(_operation_error_result(legacy_path, target_path, exc))
                return _payload(
                    root,
                    dry_run=False,
                    results=journal,
                    error=_error(exc),
                )
            journal.append(raced)
            if raced["status"] == "unchanged":
                continue
            if raced["status"] == "conflict":
                return _payload(root, dry_run=False, results=journal)
            journal.pop()
            exc = RaceLostError(
                f"legacy path disappeared after FileExistsError: {legacy_path}"
            )
            journal.append(_operation_error_result(legacy_path, target_path, exc))
            return _payload(
                root,
                dry_run=False,
                results=journal,
                error=_error(exc),
            )
        except (OSError, RuntimeError) as exc:
            journal.append(_operation_error_result(legacy_path, target_path, exc))
            return _payload(
                root,
                dry_run=False,
                results=journal,
                error=_error(exc),
            )
        else:
            journal.append(
                _result(
                    legacy_path,
                    target_path,
                    "created",
                    "created target directory and relative symlink",
                )
            )

    return _payload(root, dry_run=False, results=journal)


def bootstrap_local_assets(
    root: Path | str | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    try:
        project_root = _resolved_root(root)
    except (OSError, RuntimeError) as exc:
        root_text = str(root) if root is not None else str(Path(__file__).resolve().parents[1])
        return _payload(
            root_text,
            dry_run=dry_run,
            results=[],
            error=_error(exc),
        )

    try:
        _validate_project_root(project_root)
        plan = _preflight(project_root)
    except (OSError, RuntimeError) as exc:
        return _payload(
            project_root,
            dry_run=dry_run,
            results=[],
            error=_error(exc),
        )

    if any(result["status"] == "conflict" for result in plan):
        return _payload(project_root, dry_run=dry_run, results=plan)
    return _mutate(project_root, plan, dry_run=dry_run)


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
    payload = bootstrap_local_assets(args.root, dry_run=args.dry_run)
    _print_json(payload)
    if payload["error"] is not None:
        error = payload["error"]
        print(
            f"local asset bootstrap failed: {error['type']}: {error['message']}",
            file=sys.stderr,
        )
        return 2
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
