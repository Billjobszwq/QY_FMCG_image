"""SAM 证据链：内容哈希 + 追加式 JSONL 保存（手册§七、§一.11）。

EvidenceStore 只有 append，不提供覆盖/删除接口；同一实例重跑追加新
记录，历史永不改写。"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def mask_sha256(mask: np.ndarray) -> str:
    """mask 内容哈希（确定性：按 C-order uint8 字节）。"""
    b = np.ascontiguousarray(mask.astype(np.uint8)).tobytes()
    return hashlib.sha256(b).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    """单实例 SAM 证据（手册§七必须保留项的子集，全部必填）。"""
    photo_id: str
    image_sha256: str
    instance_id: str
    original_point: tuple
    prompts: dict
    model_id: str
    checkpoint_sha256: str
    code_commit: str
    params: dict
    candidates: list            # 全部候选（含 mask_sha256、得分、bbox、拒绝原因）
    selection_reason: str
    rules_version: str
    auto_box: tuple | None = None


class EvidenceStore:
    """追加式证据库（JSONL，一行一条记录）。"""

    def __init__(self, path):
        self.path = Path(path)

    def append(self, rec: EvidenceRecord) -> None:
        if not _SHA_RE.match(rec.image_sha256):
            raise ValueError(f"image_sha256 非法: {rec.image_sha256!r}")
        if not _SHA_RE.match(rec.checkpoint_sha256):
            raise ValueError(f"checkpoint_sha256 非法: {rec.checkpoint_sha256!r}")
        payload = asdict(rec)
        payload["timestamp"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_all(self) -> list:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in
                self.path.read_text(encoding="utf-8").strip().splitlines()]
