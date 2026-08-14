from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath

import pytest

import src.common.release_tree_audit as release_audit
from src.common.release_tree_audit import (
    Finding,
    audit_git_tree,
    audit_paths,
    blocked_path_rule,
    findings_as_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "audit_release_tree.py"


def _github_token(prefix: str = "ghp_") -> str:
    return prefix + "a_" + "b" * 18


def _aws_key() -> str:
    return "AK" + "IA" + "1234567890ABCDEF"


def _private_key_marker(algorithm: str | None = None, *, framed: bool = False) -> str:
    words = ["BEGIN"]
    if algorithm is not None:
        words.append(algorithm)
    words.extend(["PRIVATE", "KEY"])
    marker = " ".join(words)
    return "-----" + marker + "-----" if framed else marker


def _legacy_path(user: str = "alice") -> str:
    return "/" + "/".join(["Users", user, "Documents", "QY", "项目", "LLM-Image"])


def _credential_uri(
    scheme: str = "postgresql", user: str = "alice", password: str = "real-password"
) -> str:
    return scheme + ":" + "//" + user + ":" + password + "@host/db"


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
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".wav",
        ".mp3",
        ".m4a",
        ".webp",
        ".gif",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",
        ".ckpt",
        ".bin",
        ".engine",
        ".npy",
        ".npz",
        ".parquet",
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


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "config/.env.production",
        "secrets/server.pem",
        "secrets/server.KEY",
        "config/credentials.json",
        "config/credentials-prod.JSON",
        "exports/cookies.json",
        "exports/cookies-browser.json",
    ],
)
def test_credential_file_paths_are_blocked(path: str) -> None:
    assert blocked_path_rule(PurePosixPath(path)) == "credential-file"


def test_env_example_path_is_allowed() -> None:
    assert blocked_path_rule(PurePosixPath("config/.env.example")) is None


@pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"])
def test_audit_paths_finds_github_credentials(tmp_path: Path, prefix: str) -> None:
    _write(tmp_path, "docs/config.txt", _github_token(prefix))

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "credential-pattern"
    ]


@pytest.mark.parametrize(
    "secret",
    [
        _aws_key(),
        _private_key_marker(framed=True),
        _private_key_marker("RSA", framed=True),
        _private_key_marker("EC", framed=True),
        _private_key_marker("OPENSSH", framed=True),
        _private_key_marker(),
        _private_key_marker("RSA"),
        _private_key_marker("EC"),
        _private_key_marker("OPENSSH"),
    ],
)
def test_audit_paths_finds_other_credentials(tmp_path: Path, secret: str) -> None:
    _write(tmp_path, "docs/config.txt", secret)

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "credential-pattern"
    ]


@pytest.mark.parametrize("scheme", ["postgresql", "https", "custom+tls"])
def test_audit_paths_finds_embedded_uri_credentials(tmp_path: Path, scheme: str) -> None:
    _write(tmp_path, "docs/config.txt", _credential_uri(scheme=scheme))

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "credential-pattern"
    ]


@pytest.mark.parametrize(
    ("user", "password"),
    [
        ("user", "real-password"),
        ("alice", "password"),
    ],
)
def test_audit_paths_rejects_mixed_placeholder_uri_credentials(
    tmp_path: Path, user: str, password: str
) -> None:
    _write(tmp_path, "docs/config.txt", _credential_uri(user=user, password=password))

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "credential-pattern"
    ]


@pytest.mark.parametrize(
    ("user", "password"),
    [
        ("user", "password"),
        ("username", "changeme"),
        ("example-user", "example-password"),
    ],
)
def test_env_example_placeholders_are_safe(
    tmp_path: Path, user: str, password: str
) -> None:
    path = "config/.env.example"
    _write(tmp_path, path, "DATABASE_URL=" + _credential_uri(user=user, password=password))

    assert audit_paths(tmp_path, [path]) == []


@pytest.mark.parametrize(
    "content",
    [
        _legacy_path() + "/output",
        _legacy_path("Alice Smith"),
        'legacy="' + _legacy_path() + '";',
        "legacy path: " + _legacy_path() + "),",
    ],
)
def test_audit_paths_finds_legacy_absolute_path(tmp_path: Path, content: str) -> None:
    _write(tmp_path, "docs/config.txt", content)

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "legacy-absolute-path"
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("trace_id", "tr-abc123"),
        ("created_by", "operator-7"),
        ("file_count", 3),
    ],
)
def test_audit_paths_finds_concrete_runtime_values(
    tmp_path: Path, key: str, value: str | int
) -> None:
    _write(tmp_path, "docs/config.txt", json.dumps({key: value}))

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/config.txt"])] == [
        "runtime-evidence"
    ]


@pytest.mark.parametrize(
    "path",
    [
        "src/platform/runtime_schema.py",
        "tests/platform/test_runtime_schema.py",
        "scripts/export_runtime_schema.py",
        "web/src/runtimeSchema.ts",
    ],
)
def test_runtime_variable_definitions_are_allowed_in_program_sources(
    tmp_path: Path, path: str
) -> None:
    _write(
        tmp_path,
        path,
        'record = {"trace' + '_id": result.get("trace_id"), '
        '"created_by": actor, "file_count": len(files)}\n',
    )

    assert audit_paths(tmp_path, [path]) == []


def test_concrete_runtime_record_in_source_file_is_blocked(tmp_path: Path) -> None:
    path = "scripts/customer_export.py"
    _write(
        tmp_path,
        path,
        'record = {"trace' + '_id": "tr-source123", '
        '"created' + '_by": "operator-' + '9", "file' + '_count": 12}\n',
    )

    assert [finding.rule for finding in audit_paths(tmp_path, [path])] == [
        "runtime-evidence"
    ]


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        ("src/customer-export.json", "trace_id", "tr-nested123"),
        ("scripts/runtime-capture.txt", "created_by", "operator-7"),
        ("web/customer-export.json", "file_count", 42),
        ("tests/customer-dump.json", "trace_id", "tr-nested456"),
        (
            "docs/implementation/platform-runtime/customer-run.md",
            "created_by",
            "operator-8",
        ),
    ],
)
def test_runtime_values_in_nested_data_like_files_are_blocked(
    tmp_path: Path, path: str, key: str, value: str | int
) -> None:
    _write(tmp_path, path, json.dumps({key: value}))

    assert [finding.rule for finding in audit_paths(tmp_path, [path])] == [
        "runtime-evidence"
    ]


def test_runtime_placeholder_in_architecture_document_is_not_evidence(
    tmp_path: Path,
) -> None:
    path = "docs/implementation/platform-runtime/04-API-CONTRACTS.md"
    _write(tmp_path, path, json.dumps({"trace" + "_id": "..."}))

    assert audit_paths(tmp_path, [path]) == []


@pytest.mark.parametrize("path", ["business-dump.json", "customer-export.txt"])
def test_runtime_json_keys_still_block_arbitrary_business_data(
    tmp_path: Path, path: str
) -> None:
    _write(tmp_path, path, json.dumps({"created" + "_by": "operator"}))

    assert [finding.rule for finding in audit_paths(tmp_path, [path])] == [
        "runtime-evidence"
    ]


def test_blocked_runtime_path_still_wins_for_source_shaped_content(tmp_path: Path) -> None:
    path = "reports/runtime_schema.py"
    _write(tmp_path, path, json.dumps({"file" + "_count": 3}))

    assert [finding.rule for finding in audit_paths(tmp_path, [path])] == [
        "runtime-evidence",
        "runtime-report",
    ]


def test_audit_paths_reports_each_distinct_content_rule_once(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/config.txt",
        _github_token()
        + "\n"
        + _legacy_path("dev")
        + "\n"
        + json.dumps({"trace" + "_id": "tr-test123"}),
    )

    findings = audit_paths(tmp_path, ["docs/config.txt"])

    assert [finding.rule for finding in findings] == [
        "credential-pattern",
        "legacy-absolute-path",
        "runtime-evidence",
    ]


def test_audit_paths_scans_credentials_larger_than_two_million_bytes(
    tmp_path: Path,
) -> None:
    secret = _github_token().encode()
    _write(tmp_path, "docs/large.txt", secret + b" " * (2_000_001 - len(secret)))

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/large.txt"])] == [
        "credential-pattern"
    ]


def test_audit_paths_scans_runtime_evidence_larger_than_two_million_bytes(
    tmp_path: Path,
) -> None:
    evidence = json.dumps({"trace" + "_id": "tr-" + "large123"}).encode()
    _write(tmp_path, "customer-export.json", evidence + b" " * (2_000_001 - len(evidence)))

    assert [finding.rule for finding in audit_paths(tmp_path, ["customer-export.json"])] == [
        "runtime-evidence"
    ]


def test_audit_paths_fails_closed_for_nul_delimited_binary_content(tmp_path: Path) -> None:
    _write(tmp_path, "docs/binary.txt", b"\x00\xff\xfe" + _github_token().encode())

    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/binary.txt"])] == [
        "unclassified-binary"
    ]


def test_audit_paths_scans_decodable_content_around_invalid_utf8(tmp_path: Path) -> None:
    _write(tmp_path, "docs/invalid-utf8.txt", b"\xff" + _aws_key().encode() + b"\xfe")

    assert [
        finding.rule for finding in audit_paths(tmp_path, ["docs/invalid-utf8.txt"])
    ] == ["credential-pattern", "unclassified-binary"]


def test_test_file_path_has_no_content_exemption(tmp_path: Path) -> None:
    fixture_path = "tests/unit/test_release_tree_audit.py"
    _write(tmp_path, fixture_path, _github_token())

    assert [finding.rule for finding in audit_paths(tmp_path, [fixture_path])] == [
        "credential-pattern"
    ]


def test_auditor_source_and_tests_do_not_trigger_content_rules() -> None:
    source_paths = [
        "src/common/release_tree_audit.py",
        "tests/unit/test_release_tree_audit.py",
    ]

    assert audit_paths(REPO_ROOT, source_paths) == []


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


def test_audit_git_tree_scans_staged_blob_instead_of_safe_worktree(tmp_path: Path) -> None:
    path = "docs/config.txt"
    _init_git_repo(tmp_path, {path: "safe\n"})
    _write(tmp_path, path, _github_token())
    _git(tmp_path, "add", "--", path)
    _write(tmp_path, path, "safe worktree\n")

    assert [finding.rule for finding in audit_git_tree(tmp_path)] == [
        "credential-pattern"
    ]


def test_audit_git_tree_scans_index_blob_when_worktree_file_is_deleted(tmp_path: Path) -> None:
    path = "docs/config.txt"
    _init_git_repo(tmp_path, {path: _github_token()})
    (tmp_path / path).unlink()

    assert [finding.rule for finding in audit_git_tree(tmp_path)] == [
        "credential-pattern"
    ]


def test_audit_git_tree_fails_closed_for_invalid_utf8_index_blob(tmp_path: Path) -> None:
    _init_git_repo(tmp_path, {"docs/blob.dat": b"\xff\xfe"})

    assert [finding.rule for finding in audit_git_tree(tmp_path)] == [
        "unclassified-binary"
    ]


def test_audit_git_tree_rejects_symlink_after_scanning_link_blob(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    link_path = tmp_path / "credential-link"
    link_path.symlink_to(_github_token())
    _git(tmp_path, "add", "--", link_path.name)

    assert [finding.rule for finding in audit_git_tree(tmp_path)] == [
        "credential-pattern",
        "tracked-symlink",
    ]


def test_parse_and_audit_synthetic_gitlink_entry(tmp_path: Path) -> None:
    raw = b"160000 " + b"a" * 40 + b" 0\tvendor/submodule\0"

    entries = release_audit._parse_index_entries(raw)
    findings = release_audit._audit_index_entries(tmp_path, entries)

    assert entries[0].mode == "160000"
    assert [finding.rule for finding in findings] == ["gitlink"]


def test_parse_and_audit_nonzero_stage_entry(tmp_path: Path) -> None:
    raw = b"160000 " + b"b" * 40 + b" 2\tvendor/conflicted\0"

    entries = release_audit._parse_index_entries(raw)
    findings = release_audit._audit_index_entries(tmp_path, entries)

    assert entries[0].stage == 2
    assert [finding.rule for finding in findings] == ["gitlink", "unmerged-index-entry"]


def test_cat_file_failure_becomes_audit_read_error(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    raw = b"100644 " + b"0" * 40 + b" 0\tdocs/missing.txt\0"

    findings = release_audit._audit_index_entries(
        tmp_path, release_audit._parse_index_entries(raw)
    )

    assert [finding.rule for finding in findings] == ["audit-read-error"]


def test_missing_worktree_file_becomes_audit_read_error(tmp_path: Path) -> None:
    assert [finding.rule for finding in audit_paths(tmp_path, ["docs/missing.txt"])] == [
        "audit-read-error"
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
