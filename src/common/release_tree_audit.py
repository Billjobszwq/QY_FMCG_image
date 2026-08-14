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


@dataclass(frozen=True)
class _IndexEntry:
    mode: str
    object_id: str
    stage: int
    path: str


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
}

_RUNTIME_EVIDENCE_NAMES = {"EXECUTION-LOG.md", "FINAL-REPORT.md", "STATUS.md"}

_PRIVATE_KEY_WORDS = "PRIVATE" + " KEY"
_CREDENTIAL_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(
        rf"BEGIN (?:(?:RSA|EC|OPENSSH) )?{_PRIVATE_KEY_WORDS}"
    ),
)
_LEGACY_ABSOLUTE_PATH = re.compile(r"/Users/[^/\r\n]+/Documents/QY/项目/LLM-Image")
_RUNTIME_JSON_VALUE = re.compile(
    r'"(?P<key>trace_id|created_by|file_count)"\s*:\s*'
    r'(?P<value>"(?:\\.|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)'
)
_REALISTIC_TRACE_ID = re.compile(r"tr-[A-Za-z0-9_-]{6,}")
_URI_CREDENTIALS = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+.-]*:" + r"//" + r"([^\s/:@]+):([^\s/@]+)@"
)
_PLACEHOLDER_VALUES = {
    "user",
    "username",
    "password",
    "passwd",
    "changeme",
    "change-me",
    "example",
    "example-user",
    "example-password",
    "your-user",
    "your-password",
    "replace-me",
    "replace_me",
    "xxx",
    "***",
}


def _is_credential_file(path: PurePosixPath) -> bool:
    name = path.name
    lower_name = name.lower()
    if name == ".env.example":
        return False
    if lower_name == ".env" or lower_name.startswith(".env."):
        return True
    if path.suffix.lower() in {".pem", ".key"}:
        return True
    return bool(re.fullmatch(r"(?:credentials|cookies).*\.json", lower_name))


def blocked_path_rule(path: PurePosixPath) -> str | None:
    parts = path.parts
    if _is_credential_file(path):
        return "credential-file"

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
    if rule == "credential-file":
        return "path is a credential or cookie file"
    return "path contains runtime execution evidence"


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        normalized in _PLACEHOLDER_VALUES
        or normalized.startswith(("${", "{{", "<"))
        or "placeholder" in normalized
    )


def _has_uri_credentials(content: str) -> bool:
    return any(
        not _is_placeholder(match.group(1)) or not _is_placeholder(match.group(2))
        for match in _URI_CREDENTIALS.finditer(content)
    )


def _has_runtime_evidence(content: str) -> bool:
    for match in _RUNTIME_JSON_VALUE.finditer(content):
        key = match.group("key")
        raw_value = match.group("value")
        if key == "file_count":
            if not raw_value.startswith('"'):
                return True
            continue
        if not raw_value.startswith('"'):
            continue
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            continue
        if key == "trace_id":
            if _REALISTIC_TRACE_ID.fullmatch(value):
                return True
            continue
        if value not in {"", "..."} and not _is_placeholder(value):
            return True
    return False


def _text_findings(relative_path: str, content: str) -> list[Finding]:
    findings: list[Finding] = []
    if any(pattern.search(content) for pattern in _CREDENTIAL_PATTERNS) or _has_uri_credentials(
        content
    ):
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
    if _has_runtime_evidence(content):
        findings.append(
            Finding(relative_path, "runtime-evidence", "text contains a runtime evidence JSON key")
        )
    return findings


def _blob_findings(relative_path: str, raw_content: bytes) -> list[Finding]:
    if b"\x00" in raw_content:
        return [
            Finding(
                relative_path,
                "unclassified-binary",
                "tracked blob contains NUL bytes",
            )
        ]

    invalid_utf8 = False
    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        invalid_utf8 = True
        content = raw_content.decode("utf-8", errors="ignore")

    findings = _text_findings(relative_path, content)
    if invalid_utf8:
        findings.append(
            Finding(
                relative_path,
                "unclassified-binary",
                "tracked blob is not valid UTF-8 text",
            )
        )
    return findings


def _worktree_content_findings(root: Path, relative_path: str) -> list[Finding]:

    local_path = root / relative_path
    try:
        file_stat = local_path.lstat()
        if not stat.S_ISREG(file_stat.st_mode):
            return [
                Finding(relative_path, "audit-read-error", "worktree path is not a regular file")
            ]
        raw_content = local_path.read_bytes()
    except OSError as exc:
        return [
            Finding(relative_path, "audit-read-error", f"cannot read worktree file: {exc}")
        ]
    return _blob_findings(relative_path, raw_content)


def audit_paths(root: Path, tracked_paths: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in sorted(set(tracked_paths)):
        posix_path = PurePosixPath(relative_path)
        path_rule = blocked_path_rule(posix_path)
        if path_rule is not None:
            findings.append(Finding(relative_path, path_rule, _path_detail(posix_path, path_rule)))
        findings.extend(_worktree_content_findings(root, relative_path))

    return sorted(findings, key=lambda finding: (finding.path, finding.rule, finding.detail))


def _parse_index_entries(output: bytes) -> list[_IndexEntry]:
    entries: list[_IndexEntry] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode_bytes, object_id_bytes, stage_bytes = metadata.split(b" ")
            mode = mode_bytes.decode("ascii")
            object_id = object_id_bytes.decode("ascii")
            stage = int(stage_bytes.decode("ascii"))
            path = encoded_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("git ls-files --stage returned an invalid index entry") from exc
        if (
            not re.fullmatch(r"[0-7]{6}", mode)
            or not re.fullmatch(r"[0-9a-fA-F]{40,64}", object_id)
            or stage not in {0, 1, 2, 3}
        ):
            raise RuntimeError("git ls-files --stage returned an invalid index entry")
        entries.append(_IndexEntry(mode, object_id, stage, path))
    return entries


def _read_index_blob(root: Path, object_id: str) -> tuple[bytes | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", object_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return None, str(exc)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        return None, error or "git cat-file failed"
    return result.stdout, None


def _audit_index_entries(root: Path, entries: Sequence[_IndexEntry]) -> list[Finding]:
    findings: list[Finding] = []
    blob_cache: dict[str, tuple[bytes | None, str | None]] = {}
    for entry in sorted(
        entries, key=lambda item: (item.path, item.stage, item.mode, item.object_id)
    ):
        path = PurePosixPath(entry.path)
        path_rule = blocked_path_rule(path)
        if path_rule is not None:
            findings.append(Finding(entry.path, path_rule, _path_detail(path, path_rule)))

        if entry.stage != 0:
            findings.append(
                Finding(
                    entry.path,
                    "unmerged-index-entry",
                    "tracked path has a nonzero Git index stage",
                )
            )

        if entry.mode == "160000":
            findings.append(
                Finding(entry.path, "gitlink", "tracked path is a Git submodule link")
            )
            continue

        if entry.mode != "120000" and not entry.mode.startswith("100"):
            findings.append(
                Finding(entry.path, "audit-read-error", f"unsupported Git mode {entry.mode}")
            )
            continue

        if entry.object_id not in blob_cache:
            blob_cache[entry.object_id] = _read_index_blob(root, entry.object_id)
        raw_content, read_error = blob_cache[entry.object_id]
        if raw_content is None:
            findings.append(
                Finding(
                    entry.path,
                    "audit-read-error",
                    f"cannot read index blob {entry.object_id}: {read_error}",
                )
            )
        else:
            findings.extend(_blob_findings(entry.path, raw_content))

        if entry.mode == "120000":
            findings.append(
                Finding(entry.path, "tracked-symlink", "tracked path is a symbolic link")
            )

    return sorted(set(findings), key=lambda finding: (finding.path, finding.rule, finding.detail))


def audit_git_tree(root: Path) -> list[Finding]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z", "--"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed for {root}: {error or 'unknown git error'}")

    return _audit_index_entries(root, _parse_index_entries(result.stdout))


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
