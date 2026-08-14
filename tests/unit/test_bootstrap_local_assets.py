from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.bootstrap_local_assets import LEGACY_LINKS, bootstrap_local_assets


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "bootstrap_local_assets.py"
EXPECTED_LEGACY_LINKS = {
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


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--root", str(root), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _result_by_legacy_path(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    results = payload["results"]
    assert isinstance(results, list)
    return {result["legacy_path"]: result for result in results}


def test_legacy_links_match_the_compatibility_contract_exactly() -> None:
    assert LEGACY_LINKS == EXPECTED_LEGACY_LINKS
    assert list(LEGACY_LINKS) == list(EXPECTED_LEGACY_LINKS)


def test_bootstrap_creates_targets_and_relative_legacy_symlinks(tmp_path: Path) -> None:
    payload = bootstrap_local_assets(tmp_path)

    assert payload["ok"] is True
    assert payload["root"] == str(tmp_path.resolve())
    assert [result["status"] for result in payload["results"]] == [
        "created"
    ] * len(EXPECTED_LEGACY_LINKS)
    for legacy_path, target_path in EXPECTED_LEGACY_LINKS.items():
        target = tmp_path / target_path
        legacy = tmp_path / legacy_path
        assert target.is_dir()
        assert legacy.is_symlink()
        link_text = os.readlink(legacy)
        assert not Path(link_text).is_absolute()
        assert link_text == os.path.relpath(target, start=legacy.parent)
        assert legacy.resolve() == target.resolve()


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    first = bootstrap_local_assets(tmp_path)
    second = bootstrap_local_assets(tmp_path)

    assert {result["status"] for result in first["results"]} == {"created"}
    assert {result["status"] for result in second["results"]} == {"unchanged"}


def test_dry_run_reports_plan_without_any_filesystem_mutation(tmp_path: Path) -> None:
    root = tmp_path / "empty root"
    root.mkdir()
    before = list(root.iterdir())

    payload = bootstrap_local_assets(root, dry_run=True)

    assert payload["ok"] is True
    assert [result["status"] for result in payload["results"]] == [
        "created"
    ] * len(EXPECTED_LEGACY_LINKS)
    assert all(
        result["detail"] == "would create target directory and relative symlink"
        for result in payload["results"]
    )
    assert list(root.iterdir()) == before


def test_correct_relative_symlink_is_unchanged(tmp_path: Path) -> None:
    legacy_path, target_path = next(iter(EXPECTED_LEGACY_LINKS.items()))
    target = tmp_path / target_path
    target.mkdir(parents=True)
    legacy = tmp_path / legacy_path
    legacy.symlink_to(os.path.relpath(target, start=legacy.parent))

    payload = bootstrap_local_assets(tmp_path)

    result = _result_by_legacy_path(payload)[legacy_path]
    assert result["status"] == "unchanged"
    assert os.readlink(legacy) == target_path


@pytest.mark.parametrize("link_target", ["elsewhere", "missing/place"])
def test_wrong_or_broken_symlink_is_a_conflict_without_replacement(
    tmp_path: Path, link_target: str
) -> None:
    legacy_path = ".models"
    if link_target == "elsewhere":
        (tmp_path / link_target).mkdir()
    legacy = tmp_path / legacy_path
    legacy.symlink_to(link_target)

    payload = bootstrap_local_assets(tmp_path)

    result = _result_by_legacy_path(payload)[legacy_path]
    assert payload["ok"] is False
    assert result["status"] == "conflict"
    assert legacy.is_symlink()
    assert os.readlink(legacy) == link_target


def test_absolute_symlink_to_expected_target_is_a_conflict(tmp_path: Path) -> None:
    target = tmp_path / EXPECTED_LEGACY_LINKS[".models"]
    target.mkdir(parents=True)
    legacy = tmp_path / ".models"
    legacy.symlink_to(target.resolve())

    payload = bootstrap_local_assets(tmp_path)

    assert _result_by_legacy_path(payload)[".models"]["status"] == "conflict"
    assert os.readlink(legacy) == str(target.resolve())


@pytest.mark.parametrize("entity_kind", ["file", "directory"])
def test_real_file_or_directory_is_a_conflict_without_mutation(
    tmp_path: Path, entity_kind: str
) -> None:
    legacy = tmp_path / ".datasets"
    if entity_kind == "file":
        legacy.write_text("keep me", encoding="utf-8")
    else:
        legacy.mkdir()
        (legacy / "keep.txt").write_text("keep me", encoding="utf-8")

    payload = bootstrap_local_assets(tmp_path)

    result = _result_by_legacy_path(payload)[".datasets"]
    assert payload["ok"] is False
    assert result["status"] == "conflict"
    if entity_kind == "file":
        assert legacy.read_text(encoding="utf-8") == "keep me"
    else:
        assert (legacy / "keep.txt").read_text(encoding="utf-8") == "keep me"


def test_bootstrap_handles_spaces_and_non_ascii_in_root_path(tmp_path: Path) -> None:
    root = tmp_path / "资产 workspace with spaces"
    root.mkdir()

    payload = bootstrap_local_assets(root)

    assert payload["ok"] is True
    assert payload["root"] == str(root.resolve())
    assert (root / ".models").resolve() == (root / "recognition-models/registry").resolve()


def test_json_output_is_deterministic_and_has_stable_key_order(tmp_path: Path) -> None:
    root = tmp_path / "deterministic"
    root.mkdir()

    first = _run_cli(root, "--dry-run")
    second = _run_cli(root, "--dry-run")

    assert first.returncode == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert list(payload) == ["ok", "root", "results"]
    assert [list(result) for result in payload["results"]] == [
        ["legacy_path", "target_path", "status", "detail"]
    ] * len(EXPECTED_LEGACY_LINKS)
    assert [result["legacy_path"] for result in payload["results"]] == list(
        EXPECTED_LEGACY_LINKS
    )


def test_cli_returns_zero_for_success_and_one_for_conflict(tmp_path: Path) -> None:
    success_root = tmp_path / "success"
    success_root.mkdir()
    success = _run_cli(success_root)

    conflict_root = tmp_path / "conflict"
    conflict_root.mkdir()
    conflict_file = conflict_root / ".models"
    conflict_file.write_text("keep", encoding="utf-8")
    conflict = _run_cli(conflict_root)

    assert success.returncode == 0
    assert json.loads(success.stdout)["ok"] is True
    assert conflict.returncode == 1
    assert json.loads(conflict.stdout)["ok"] is False
    assert conflict_file.read_text(encoding="utf-8") == "keep"


def test_cli_returns_two_for_an_invalid_root(tmp_path: Path) -> None:
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("content", encoding="utf-8")

    completed = _run_cli(invalid_root)

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "ok": False,
        "root": str(invalid_root.resolve()),
        "results": [],
    }
    assert "project root is not a directory" in completed.stderr
