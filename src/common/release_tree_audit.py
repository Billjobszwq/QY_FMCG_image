from __future__ import annotations

import json
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    detail: str


_ALLOWED_LOCAL_DOCS = {
    PurePosixPath("training-data/README.md"),
    PurePosixPath("recognition-models/README.md"),
    PurePosixPath("runtime/README.md"),
}

_BLOCKED_ROOTS = {
    "reports": "runtime-report",
    ".review_queue": "user-review-data",
    ".data_protocol": "dataset-entity",
    ".datasets_nextgen": "dataset-entity",
    ".micro_gold_v2": "dataset-entity",
    "training-data": "training-data-entity",
    "recognition-models": "model-weight",
    "runtime": "runtime-state",
}

_BLOCKED_SUFFIXES = {
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
}

_RUNTIME_EVIDENCE_NAMES = {"EXECUTION-LOG.md", "FINAL-REPORT.md", "STATUS.md"}
_CONTENT_SCAN_EXEMPTIONS = {"tests/unit/test_release_tree_audit.py"}
_MAX_TEXT_BYTES = 2_000_000

_PRIVATE_KEY_WORDS = "PRIVATE" + " KEY"
_CREDENTIAL_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(
        rf"BEGIN (?:(?:RSA|EC|OPENSSH) )?{_PRIVATE_KEY_WORDS}"
    ),
)
_LEGACY_ABSOLUTE_PATH = re.compile(r"/Users/[^/\r\n]+/Documents/QY/项目/LLM-Image")
_RUNTIME_JSON_KEY = re.compile(r'"(?:trace_id|created_by|file_count)"\s*:')


def blocked_path_rule(path: PurePosixPath) -> str | None:
    parts = path.parts
    if (
        (
            len(parts) >= 3
            and parts[:2] == ("docs", "implementation")
            and path.name in _RUNTIME_EVIDENCE_NAMES
        )
        or "before-snapshots" in parts
        or "after-snapshots" in parts
        or any(
            parts[index : index + 2] == ("execution", "evidence")
            for index in range(len(parts) - 1)
        )
    ):
        return "runtime-evidence"

    if path in _ALLOWED_LOCAL_DOCS:
        return None

    if parts and parts[0] in _BLOCKED_ROOTS:
        return _BLOCKED_ROOTS[parts[0]]

    if path.suffix.lower() in _BLOCKED_SUFFIXES:
        return "forbidden-binary-or-business-data"

    return None


def _path_detail(path: PurePosixPath, rule: str) -> str:
    if path.parts and path.parts[0] in _BLOCKED_ROOTS and rule == _BLOCKED_ROOTS[path.parts[0]]:
        return f"path is under blocked root '{path.parts[0]}'"
    if rule == "forbidden-binary-or-business-data":
        return f"blocked file suffix '{path.suffix.lower()}'"
    return "path contains runtime execution evidence"


def _content_findings(root: Path, relative_path: str) -> list[Finding]:
    if relative_path in _CONTENT_SCAN_EXEMPTIONS:
        return []

    local_path = root / relative_path
    try:
        file_stat = local_path.lstat()
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > _MAX_TEXT_BYTES:
            return []
        raw_content = local_path.read_bytes()
        if b"\x00" in raw_content:
            return []
        content = raw_content.decode("utf-8", errors="ignore")
    except OSError:
        return []

    findings: list[Finding] = []
    if any(pattern.search(content) for pattern in _CREDENTIAL_PATTERNS):
        findings.append(
            Finding(relative_path, "credential-pattern", "text contains a credential pattern")
        )
    if _LEGACY_ABSOLUTE_PATH.search(content):
        findings.append(
            Finding(
                relative_path,
                "legacy-absolute-path",
                "text contains an absolute path to the legacy repository",
            )
        )
    if _RUNTIME_JSON_KEY.search(content):
        findings.append(
            Finding(relative_path, "runtime-evidence", "text contains a runtime evidence JSON key")
        )
    return findings


def audit_paths(root: Path, tracked_paths: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in sorted(set(tracked_paths)):
        posix_path = PurePosixPath(relative_path)
        path_rule = blocked_path_rule(posix_path)
        if path_rule is not None:
            findings.append(Finding(relative_path, path_rule, _path_detail(posix_path, path_rule)))
        findings.extend(_content_findings(root, relative_path))

    return sorted(findings, key=lambda finding: (finding.path, finding.rule, finding.detail))


def audit_git_tree(root: Path) -> list[Finding]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed for {root}: {error or 'unknown git error'}")

    try:
        tracked_paths = [
            encoded_path.decode("utf-8") for encoded_path in result.stdout.split(b"\0") if encoded_path
        ]
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"git ls-files returned a non-UTF-8 path for {root}") from exc

    return audit_paths(root, tracked_paths)


def findings_as_json(findings: Sequence[Finding]) -> str:
    ordered_findings = sorted(findings, key=lambda finding: (finding.path, finding.rule, finding.detail))
    return json.dumps(
        {
            "ok": not ordered_findings,
            "finding_count": len(ordered_findings),
            "findings": [asdict(finding) for finding in ordered_findings],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
