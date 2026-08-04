"""质量证据链存储（手册§八 / §十）：

- 每张图的判定追加一条 JSONL，含原图哈希、原始指标、策略/分析器版本、
  触发信号与结论、时间戳与来源 URI；
- append-only：重算只追加新证据，永不改写历史（无 delete/overwrite 接口）；
- 原图内容寻址路径：<blobs>/<sha[:2]>/<sha>，原图永不删除/移动。"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .contracts import VERDICTS

BLOB_ROOT = Path(".quality/blobs")


def original_blob_path(image_sha256: str, root: Path = BLOB_ROOT) -> Path:
    """内容寻址原图路径（两级分片：<sha[:2]>/<sha>）。"""
    sha = image_sha256.lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError(f"非法 image_sha256: {image_sha256!r}")
    return root / sha[:2] / sha


class QualityEvidenceStore:
    """质量判定证据账本（JSONL，append-only）。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, image_sha256: str, verdict: str, findings: list,
               metrics: dict, policy_version: str, analyzer_version: str,
               source_uri: str = "", extra: dict | None = None) -> dict:
        if verdict not in VERDICTS:
            raise ValueError(f"非法 verdict: {verdict!r}，必须属于 {VERDICTS}")
        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "image_sha256": image_sha256,
            "verdict": verdict,
            "findings": [asdict(f) for f in findings],
            "metrics": dict(metrics),
            "policy_version": policy_version,
            "analyzer_version": analyzer_version,
            "source_uri": source_uri,
            "keep_original": True,
        }
        if extra:
            rec["extra"] = dict(extra)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def read_all(self) -> list:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def latest_by_sha(self) -> dict:
        """每张图取最新一条判定（账本本身仍保留全部历史）。"""
        latest: dict = {}
        for rec in self.read_all():
            latest[rec["image_sha256"]] = rec
        return latest
