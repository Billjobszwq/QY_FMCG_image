"""OSV51 C-6：证据绑定核心（binding core）。

Gate 证据链的单一算法源：git HEAD / 代码树 hash / migration hash /
worktree clean / suite 配置 hash / 命令 hash。所有证据生成器
（UAT/test/browser/negative）与 Gate 评估器共用本模块，禁止各自
复制算法（避免 recorded/current 口径漂移）。

recorded 侧永远来自证据文件中的 binding 块；current 侧由评估器现场
独立计算——消灭“同一当前值同时充当 recorded 与 current”的自比较。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

# 代码树 hash 覆盖范围（与 OSV5 Gate 3.2 口径一致）
TREE_PATHS = ("src/platform", "web/src", "scripts")


def git_head(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root),
            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def worktree_clean(root: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(root), capture_output=True, text=True,
            timeout=10).stdout
        return out.strip() == ""
    except Exception:  # noqa: BLE001
        return False


def tree_hash(root: Path, paths=TREE_PATHS) -> str:
    h = hashlib.sha256()
    for sub in paths:
        base = root / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts \
                    and not p.name.startswith("."):
                h.update(str(p.relative_to(root)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:16]


def migration_hash(conn) -> str:
    rows = conn.execute(
        "SELECT name FROM schema_migrations ORDER BY id").fetchall()
    return hashlib.sha256(
        ",".join(r["name"] for r in rows).encode()).hexdigest()[:16]


def suite_config_hash(root: Path) -> str:
    """pytest 套件口径 hash（pyproject [tool.pytest.ini_options]）。"""
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        text = ""
    seg: list[str] = []
    insec = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            insec = s == "[tool.pytest.ini_options]"
            continue
        if insec:
            seg.append(s)
    return hashlib.sha256("\n".join(seg).encode()).hexdigest()[:16]


def command_hash(argv: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(argv, ensure_ascii=False).encode()).hexdigest()[:16]


def result_hash(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   default=str).encode()).hexdigest()[:16]


def make_binding(*, root: Path, conn=None, store=None,
                 argv: list[str], result_payload=None,
                 started_at: str = "", finished_at: str = "",
                 database_fingerprint: dict | None = None) -> dict:
    """组装证据 binding 块。database_fingerprint 由调用方通过
    gate_evaluator.db_fingerprint(store) 提供（避免本模块反向依赖）。"""
    b = {
        "source_commit": git_head(root),
        "code_tree_hash": tree_hash(root),
        "migration_hash": migration_hash(conn) if conn is not None
        else "",
        "suite_config_hash": suite_config_hash(root),
        "command_hash": command_hash(argv),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    if database_fingerprint is not None:
        b["database_fingerprint"] = database_fingerprint
    if result_payload is not None:
        b["result_hash"] = result_hash(result_payload)
    return b
