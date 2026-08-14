from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.bootstrap_local_assets as bootstrap_module
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


def _make_project_root(path: Path) -> Path:
    path.mkdir()
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "scripts").mkdir()
    return path


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


def _filesystem_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            snapshot.append((relative, "directory", ""))
        else:
            snapshot.append((relative, "file", path.read_text(encoding="utf-8")))
    return snapshot


def test_legacy_links_match_the_compatibility_contract_exactly() -> None:
    assert LEGACY_LINKS == EXPECTED_LEGACY_LINKS
    assert list(LEGACY_LINKS) == list(EXPECTED_LEGACY_LINKS)


def test_bootstrap_creates_targets_and_relative_legacy_symlinks(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "project")

    payload = bootstrap_local_assets(root)

    assert payload["ok"] is True
    assert payload["root"] == str(root.resolve())
    assert payload["dry_run"] is False
    assert payload["error"] is None
    assert [result["status"] for result in payload["results"]] == [
        "created"
    ] * len(EXPECTED_LEGACY_LINKS)
    for legacy_path, target_path in EXPECTED_LEGACY_LINKS.items():
        target = root / target_path
        legacy = root / legacy_path
        assert target.is_dir()
        assert legacy.is_symlink()
        link_text = os.readlink(legacy)
        assert not Path(link_text).is_absolute()
        assert link_text == os.path.relpath(target, start=legacy.parent)
        assert legacy.resolve() == target.resolve()


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "project")

    first = bootstrap_local_assets(root)
    second = bootstrap_local_assets(root)

    assert {result["status"] for result in first["results"]} == {"created"}
    assert {result["status"] for result in second["results"]} == {"unchanged"}


def test_dry_run_uses_machine_readable_statuses_without_mutation(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "empty root")
    before = _filesystem_snapshot(root)

    payload = bootstrap_local_assets(root, dry_run=True)

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["error"] is None
    assert [result["status"] for result in payload["results"]] == [
        "would_create"
    ] * len(EXPECTED_LEGACY_LINKS)
    assert _filesystem_snapshot(root) == before


def test_preflight_conflict_prevents_all_bootstrap_mutations(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "project")
    conflict = root / ".models"
    conflict.write_text("keep", encoding="utf-8")
    before = _filesystem_snapshot(root)

    payload = bootstrap_local_assets(root)

    results = _result_by_legacy_path(payload)
    assert payload["ok"] is False
    assert payload["error"] is None
    assert results[".models"]["status"] == "conflict"
    assert results[".datasets"]["status"] == "would_create"
    assert _filesystem_snapshot(root) == before
    assert not (root / "training-data").exists()


def test_correct_relative_symlink_is_unchanged(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "project")
    legacy_path, target_path = next(iter(EXPECTED_LEGACY_LINKS.items()))
    target = root / target_path
    target.mkdir(parents=True)
    legacy = root / legacy_path
    legacy.symlink_to(os.path.relpath(target, start=legacy.parent))

    payload = bootstrap_local_assets(root)

    result = _result_by_legacy_path(payload)[legacy_path]
    assert result["status"] == "unchanged"
    assert os.readlink(legacy) == target_path


@pytest.mark.parametrize("link_target", ["elsewhere", "missing/place"])
def test_wrong_or_broken_symlink_is_a_conflict_without_replacement(
    tmp_path: Path, link_target: str
) -> None:
    root = _make_project_root(tmp_path / "project")
    legacy_path = ".models"
    if link_target == "elsewhere":
        (root / link_target).mkdir()
    legacy = root / legacy_path
    legacy.symlink_to(link_target)
    before = _filesystem_snapshot(root)

    payload = bootstrap_local_assets(root)

    result = _result_by_legacy_path(payload)[legacy_path]
    assert payload["ok"] is False
    assert result["status"] == "conflict"
    assert _filesystem_snapshot(root) == before


def test_broken_symlink_with_expected_text_is_a_conflict(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "project")
    legacy = root / ".models"
    legacy.symlink_to(EXPECTED_LEGACY_LINKS[".models"])
    before = _filesystem_snapshot(root)

    payload = bootstrap_local_assets(root)

    assert _result_by_legacy_path(payload)[".models"]["status"] == "conflict"
    assert _filesystem_snapshot(root) == before


def test_absolute_symlink_to_expected_target_is_a_conflict(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "project")
    target = root / EXPECTED_LEGACY_LINKS[".models"]
    target.mkdir(parents=True)
    legacy = root / ".models"
    legacy.symlink_to(target.resolve())

    payload = bootstrap_local_assets(root)

    assert _result_by_legacy_path(payload)[".models"]["status"] == "conflict"
    assert os.readlink(legacy) == str(target.resolve())


@pytest.mark.parametrize("entity_kind", ["file", "directory"])
def test_real_file_or_directory_is_a_conflict_without_mutation(
    tmp_path: Path, entity_kind: str
) -> None:
    root = _make_project_root(tmp_path / "project")
    legacy = root / ".datasets"
    if entity_kind == "file":
        legacy.write_text("keep me", encoding="utf-8")
    else:
        legacy.mkdir()
        (legacy / "keep.txt").write_text("keep me", encoding="utf-8")
    before = _filesystem_snapshot(root)

    payload = bootstrap_local_assets(root)

    result = _result_by_legacy_path(payload)[".datasets"]
    assert payload["ok"] is False
    assert result["status"] == "conflict"
    assert _filesystem_snapshot(root) == before


@pytest.mark.parametrize("unsafe_kind", ["file", "symlink"])
def test_unsafe_target_component_is_a_preflight_conflict_without_mutation(
    tmp_path: Path, unsafe_kind: str
) -> None:
    root = _make_project_root(tmp_path / "project")
    component = root / "recognition-models"
    if unsafe_kind == "file":
        component.write_text("keep", encoding="utf-8")
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        component.symlink_to(outside, target_is_directory=True)
    before = _filesystem_snapshot(root)

    payload = bootstrap_local_assets(root)

    results = _result_by_legacy_path(payload)
    assert payload["ok"] is False
    assert results[".models"]["status"] == "conflict"
    assert results[".sam_checkpoints"]["status"] == "conflict"
    assert _filesystem_snapshot(root) == before
    assert not (root / "training-data").exists()


def test_unexpected_io_error_preserves_partial_mutation_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_project_root(tmp_path / "project")
    original_symlink_to = Path.symlink_to
    calls = 0

    def fail_second_symlink(
        path: Path, target: str | Path, target_is_directory: bool = False
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk failure")
        original_symlink_to(path, target, target_is_directory=target_is_directory)

    monkeypatch.setattr(Path, "symlink_to", fail_second_symlink)

    payload = bootstrap_local_assets(root)

    assert payload["ok"] is False
    assert payload["error"] == {"type": "OSError", "message": "simulated disk failure"}
    assert [(result["legacy_path"], result["status"]) for result in payload["results"]] == [
        (".models", "created"),
        (".sam_checkpoints", "error"),
    ]
    assert (root / ".models").is_symlink()
    assert not (root / ".sam_checkpoints").exists()
    assert not (root / "training-data").exists()


def test_concurrent_legacy_creation_is_rechecked_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_project_root(tmp_path / "project")
    original_symlink_to = Path.symlink_to
    raced = False

    def create_conflict_before_symlink(
        path: Path, target: str | Path, target_is_directory: bool = False
    ) -> None:
        nonlocal raced
        if not raced:
            raced = True
            path.write_text("racer", encoding="utf-8")
        original_symlink_to(path, target, target_is_directory=target_is_directory)

    monkeypatch.setattr(Path, "symlink_to", create_conflict_before_symlink)

    payload = bootstrap_local_assets(root)

    assert payload["ok"] is False
    assert payload["error"] is None
    assert [(result["legacy_path"], result["status"]) for result in payload["results"]] == [
        (".models", "conflict")
    ]
    assert (root / ".models").read_text(encoding="utf-8") == "racer"
    assert not (root / ".sam_checkpoints").exists()


def test_target_is_rechecked_immediately_before_symlink_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_project_root(tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    original_ensure_target = bootstrap_module._ensure_target_directory
    raced = False

    def replace_target_after_creation(
        project_root: Path, target_path: str
    ) -> tuple[str, str] | None:
        nonlocal raced
        outcome = original_ensure_target(project_root, target_path)
        if not raced:
            raced = True
            target = project_root / target_path
            target.rmdir()
            target.symlink_to(outside, target_is_directory=True)
        return outcome

    monkeypatch.setattr(
        bootstrap_module, "_ensure_target_directory", replace_target_after_creation
    )

    payload = bootstrap_local_assets(root)

    assert payload["ok"] is False
    assert payload["error"] is None
    assert payload["results"][0]["status"] == "conflict"
    assert not (root / ".models").exists()
    assert (root / "recognition-models/registry").is_symlink()


def test_bootstrap_handles_spaces_and_non_ascii_in_root_path(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "资产 workspace with spaces")

    payload = bootstrap_local_assets(root)

    assert payload["ok"] is True
    assert payload["root"] == str(root.resolve())
    assert (root / ".models").resolve() == (root / "recognition-models/registry").resolve()


def test_json_output_is_deterministic_and_has_stable_key_order(tmp_path: Path) -> None:
    root = _make_project_root(tmp_path / "deterministic")

    first = _run_cli(root, "--dry-run")
    second = _run_cli(root, "--dry-run")

    assert first.returncode == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert list(payload) == ["ok", "root", "dry_run", "results", "error"]
    assert [list(result) for result in payload["results"]] == [
        ["legacy_path", "target_path", "status", "detail"]
    ] * len(EXPECTED_LEGACY_LINKS)
    assert [result["legacy_path"] for result in payload["results"]] == list(
        EXPECTED_LEGACY_LINKS
    )


def test_cli_returns_zero_for_success_and_one_for_conflict(tmp_path: Path) -> None:
    success_root = _make_project_root(tmp_path / "success")
    success = _run_cli(success_root)

    conflict_root = _make_project_root(tmp_path / "conflict")
    conflict_file = conflict_root / ".models"
    conflict_file.write_text("keep", encoding="utf-8")
    conflict = _run_cli(conflict_root)

    assert success.returncode == 0
    assert json.loads(success.stdout)["ok"] is True
    assert conflict.returncode == 1
    assert json.loads(conflict.stdout)["ok"] is False
    assert conflict_file.read_text(encoding="utf-8") == "keep"
    assert not (conflict_root / "training-data").exists()


@pytest.mark.parametrize("invalid_kind", ["file", "directory"])
def test_cli_returns_two_for_invalid_or_wrong_existing_root(
    tmp_path: Path, invalid_kind: str
) -> None:
    invalid_root = tmp_path / "not-a-project"
    if invalid_kind == "file":
        invalid_root.write_text("content", encoding="utf-8")
    else:
        invalid_root.mkdir()
    before = _filesystem_snapshot(tmp_path)

    completed = _run_cli(invalid_root)

    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload["ok"] is False
    assert payload["root"] == str(invalid_root.resolve())
    assert payload["dry_run"] is False
    assert payload["results"] == []
    assert payload["error"]["type"] == "InvalidProjectRootError"
    assert "project root" in payload["error"]["message"]
    assert _filesystem_snapshot(tmp_path) == before


def test_gitignore_covers_legacy_roots_and_whitelists_readmes() -> None:
    for legacy_path in EXPECTED_LEGACY_LINKS:
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", legacy_path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert ignored.returncode == 0, legacy_path

    for path in (
        "training-data/private.bin",
        "recognition-models/private.bin",
        "runtime/private.bin",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert ignored.returncode == 0, path

    for readme in (
        "training-data/README.md",
        "recognition-models/README.md",
        "runtime/README.md",
    ):
        allowed = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", readme],
            cwd=REPO_ROOT,
            check=False,
        )
        assert allowed.returncode == 1, readme
