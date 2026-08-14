from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath

import pytest

from src.common.release_tree_audit import (
    Finding,
    audit_git_tree,
    audit_paths,
    blocked_path_rule,
    findings_as_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "audit_release_tree.py"


def _write(root: Path, relative_path: str, content: str | bytes = "safe\n") -> None:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(root: Path, tracked: dict[str, str | bytes]) -> None:
    _git(root, "init", "-q")
    for relative_path, content in tracked.items():
        _write(root, relative_path, content)
    _git(root, "add", "--", ".")


def _run_cli(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "--root", str(root), "--format", "json"],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_finding_is_immutable() -> None:
    finding = Finding(path="reports/run.txt", rule="runtime-report", detail="blocked")

    with pytest.raises(FrozenInstanceError):
        finding.path = "changed.txt"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("reports/run.txt", "runtime-report"),
        (".review_queue/item.txt", "user-review-data"),
        (".data_protocol/item.txt", "dataset-entity"),
        (".datasets_nextgen/item.txt", "dataset-entity"),
        (".micro_gold_v2/item.txt", "dataset-entity"),
        ("training-data/example.txt", "training-data-entity"),
        ("recognition-models/model.txt", "model-weight"),
        ("runtime/state.txt", "runtime-state"),
    ],
)
def test_blocked_roots(path: str, rule: str) -> None:
    assert blocked_path_rule(PurePosixPath(path)) == rule


@pytest.mark.parametrize(
    "path",
    [
        "training-data/README.md",
        "recognition-models/README.md",
        "runtime/README.md",
    ],
)
def test_allowed_local_documentation(path: str) -> None:
    assert blocked_path_rule(PurePosixPath(path)) is None


@pytest.mark.parametrize(
    "suffix",
    [
        ".pt",
        ".pth",
        ".onnx",
        ".safetensors",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".xlsx",
        ".xls",
        ".csv",
        ".jsonl",
        ".jpg",
        ".jpeg",
        ".png",
    ],
)
@pytest.mark.parametrize("uppercase", [False, True], ids=["lowercase", "uppercase"])
def test_blocked_suffixes_are_case_insensitive(suffix: str, uppercase: bool) -> None:
    actual_suffix = suffix.upper() if uppercase else suffix

    assert (
        blocked_path_rule(PurePosixPath(f"artifacts/item{actual_suffix}"))
        == "forbidden-binary-or-business-data"
    )


@pytest.mark.parametrize(
    "path",
    [
        "work/execution/evidence/result.txt",
        "work/before-snapshots/result.txt",
        "work/after-snapshots/result.txt",
        "docs/implementation/EXECUTION-LOG.md",
        "docs/implementation/milestone/FINAL-REPORT.md",
        "docs/implementation/STATUS.md",
    ],
)
def test_runtime_evidence_paths(path: str) -> None:
    assert blocked_path_rule(PurePosixPath(path)) == "runtime-evidence"


@pytest.mark.parametrize(
    "path",
    [
        "STATUS.md",
        "implementation/FINAL-REPORT.md",
        "docs/reference/EXECUTION-LOG.md",
    ],
)
def test_operational_doc_names_are_allowed_outside_docs_implementation(path: str) -> None:
    assert blocked_path_rule(PurePosixPath(path)) is None


def test_runtime_evidence_rule_takes_precedence_over_runtime_root() -> None:
    path = PurePosixPath("runtime/execution/evidence/result.txt")

    assert blocked_path_rule(path) == "runtime-evidence"


@pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"])
def test_audit_paths_finds_github_credentials(tmp_path: Path, prefix: str) -> None:
    _write(tmp_path, "docs/config.txt", prefix + "a_" + "b" * 18)

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "credential-pattern"
    ]


@pytest.mark.parametrize(
    "secret",
    [
        "AKIA1234567890ABCDEF",
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "BEGIN PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
        "BEGIN EC PRIVATE KEY",
        "BEGIN OPENSSH PRIVATE KEY",
    ],
)
def test_audit_paths_finds_other_credentials(tmp_path: Path, secret: str) -> None:
    _write(tmp_path, "docs/config.txt", secret)

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "credential-pattern"
    ]


@pytest.mark.parametrize(
    "content",
    [
        "/Users/alice/Documents/QY/项目/LLM-Image/output",
        "/Users/Alice Smith/Documents/QY/项目/LLM-Image",
        'legacy="/Users/alice/Documents/QY/项目/LLM-Image";',
        "legacy path: /Users/alice/Documents/QY/项目/LLM-Image),",
    ],
)
def test_audit_paths_finds_legacy_absolute_path(tmp_path: Path, content: str) -> None:
    _write(tmp_path, "docs/config.txt", content)

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "legacy-absolute-path"
    ]


@pytest.mark.parametrize("key", ["trace_id", "created_by", "file_count"])
def test_audit_paths_finds_runtime_json_keys(tmp_path: Path, key: str) -> None:
    _write(tmp_path, "docs/config.txt", json.dumps({key: "value"}))

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "runtime-evidence"
    ]


def test_audit_paths_reports_each_distinct_content_rule_once(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/config.txt",
        "ghp_" + "a" * 20 + '\n/Users/dev/Documents/QY/项目/LLM-Image\n{"trace_id": "x"}',
    )

    findings = audit_paths(tmp_path, ["docs/config.txt"])

    assert [finding.rule for finding in findings] == [
        "credential-pattern",
        "legacy-absolute-path",
        "runtime-evidence",
    ]


def test_audit_paths_skips_files_larger_than_two_million_bytes(tmp_path: Path) -> None:
    secret = b"ghp_" + b"a" * 20
    _write(tmp_path, "docs/large.txt", secret + b" " * (2_000_001 - len(secret)))

    assert audit_paths(tmp_path, ["docs/large.txt"]) == []


def test_audit_paths_skips_nul_delimited_binary_content(tmp_path: Path) -> None:
    _write(tmp_path, "docs/binary.txt", b"\x00\xff\xfeghp_" + b"a" * 20)

    assert audit_paths(tmp_path, ["docs/binary.txt"]) == []


def test_audit_paths_scans_decodable_content_around_invalid_utf8(tmp_path: Path) -> None:
    _write(tmp_path, "docs/invalid-utf8.txt", b"\xffAKIA1234567890ABCDEF\xfe")

    assert [
        finding.rule for finding in audit_paths(tmp_path, ["docs/invalid-utf8.txt"])
    ] == ["credential-pattern"]


def test_negative_pattern_fixture_is_exempt_from_content_scanning(tmp_path: Path) -> None:
    fixture_path = "tests/unit/test_release_tree_audit.py"
    _write(tmp_path, fixture_path, "ghp_" + "a" * 20)

    assert audit_paths(tmp_path, [fixture_path]) == []


def test_auditor_source_does_not_trigger_its_own_content_rules() -> None:
    source_path = "src/common/release_tree_audit.py"

    assert audit_paths(REPO_ROOT, [source_path]) == []


def test_negative_pattern_fixture_still_obeys_path_rules(tmp_path: Path) -> None:
    fixture_path = "tests/unit/test_release_tree_audit.py.png"
    _write(tmp_path, fixture_path, b"not an image")

    findings = audit_paths(tmp_path, [fixture_path])

    assert [finding.rule for finding in findings] == ["forbidden-binary-or-business-data"]


def test_audit_paths_is_deterministic_and_deduplicates_input(tmp_path: Path) -> None:
    _write(tmp_path, "reports/z.txt")
    _write(tmp_path, "reports/a.txt")

    findings = audit_paths(tmp_path, ["reports/z.txt", "reports/a.txt", "reports/z.txt"])

    assert findings == [
        Finding("reports/a.txt", "runtime-report", "path is under blocked root 'reports'"),
        Finding("reports/z.txt", "runtime-report", "path is under blocked root 'reports'"),
    ]


def test_findings_as_json_has_stable_schema_and_utf8() -> None:
    findings = [Finding("报告/结果.txt", "runtime-report", "包含运行报告")]

    payload = findings_as_json(findings)

    assert payload == json.dumps(
        {
            "ok": False,
            "finding_count": 1,
            "findings": [
                {"path": "报告/结果.txt", "rule": "runtime-report", "detail": "包含运行报告"}
            ],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def test_findings_as_json_reports_clean_result() -> None:
    assert json.loads(findings_as_json([])) == {
        "ok": True,
        "finding_count": 0,
        "findings": [],
    }


def test_audit_git_tree_scans_only_tracked_files_and_handles_utf8_paths(tmp_path: Path) -> None:
    _init_git_repo(
        tmp_path,
        {
            "reports/结果.txt": "safe",
            "docs/说明.txt": "safe",
        },
    )
    _write(tmp_path, "reports/untracked.txt", "ghp_" + "a" * 20)
    _write(tmp_path, "untracked.png", b"image")

    findings = audit_git_tree(tmp_path)

    assert findings == [
        Finding("reports/结果.txt", "runtime-report", "path is under blocked root 'reports'")
    ]


def test_audit_git_tree_raises_clear_error_outside_git_repository(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="git ls-files failed"):
        audit_git_tree(tmp_path)


def test_cli_returns_zero_and_json_for_clean_tree(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, {"README.md": "clean\n"})

    result = _run_cli(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"ok": True, "finding_count": 0, "findings": []}


def test_cli_returns_one_and_json_when_findings_exist(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, {"reports/run.txt": "runtime output\n"})

    result = _run_cli(tmp_path)

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["findings"] == [
        {
            "path": "reports/run.txt",
            "rule": "runtime-report",
            "detail": "path is under blocked root 'reports'",
        }
    ]


def test_cli_returns_two_with_clear_operational_error(tmp_path: Path) -> None:
    result = _run_cli(tmp_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "release-tree audit failed:" in result.stderr
    assert "git ls-files failed" in result.stderr
