"""质量流水线批量运行器（手册§八 / Gate Q0）。

- 输入：图片路径列表 + 可选 ROI 提示；输出：四级 verdict + 证据账本追加；
- 断点续跑：按 image_sha256 跳过账本中已有（相同 policy+analyzer 版本）的图；
- 只读原图，永不移动/删除；报告原子写（tmp → rename）；
- reject 仅意味着"从训练 manifest 排除"，原图保留（keep_original=True）。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import cv2

from . import analyzers
from .contracts import Finding
from .evidence import QualityEvidenceStore
from .policy import ANALYZER_VERSION, POLICY_VERSION, decide


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_image(img, roi=None):
    """运行全部分析器，汇总 findings 与 metrics。"""
    findings: list = []
    metrics: dict = {}
    for fn, needs_roi in (
        (analyzers.analyze_blur, True),
        (analyzers.analyze_exposure, True),
        (analyzers.analyze_coverage, True),
        (analyzers.analyze_tilt, False),
        (analyzers.analyze_readability, False),
        (analyzers.analyze_moire, False),
        (analyzers.analyze_big_foreground, False),
    ):
        f, m = fn(img, roi) if needs_roi else fn(img)
        findings.extend(f)
        metrics.update({f"{fn.__name__}.{k}": v for k, v in m.items()})
    return findings, metrics


def _atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


class QualityRunner:
    """批处理：process(paths) → summary；支持断点续跑。"""

    def __init__(self, store_path, policy_version: str = POLICY_VERSION,
                 analyzer_version: str = ANALYZER_VERSION):
        self.store = QualityEvidenceStore(store_path)
        self.policy_version = policy_version
        self.analyzer_version = analyzer_version

    def _done_shas(self) -> set:
        done = set()
        for rec in self.store.read_all():
            if (rec.get("policy_version") == self.policy_version
                    and rec.get("analyzer_version") == self.analyzer_version):
                done.add(rec["image_sha256"])
        return done

    def process(self, image_paths, roi_map: dict | None = None,
                source_uri_fn=None) -> dict:
        """image_paths: 路径列表；roi_map: {path_str: (x1,y1,x2,y2)}；
        source_uri_fn: path → 来源 URI（证据字段）。"""
        roi_map = roi_map or {}
        counts = {"accept": 0, "warn": 0, "manual_review": 0, "reject": 0,
                  "skipped": 0, "decode_fail": 0}
        done = self._done_shas()
        per_image = []

        for p in image_paths:
            p = Path(p)
            sha = sha256_file(p)
            if sha in done:
                counts["skipped"] += 1
                continue
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                findings = [Finding("decode_fail", "strong",
                                    recoverable=False, detail=str(p))]
                metrics: dict = {}
            else:
                findings, metrics = analyze_image(img, roi_map.get(str(p)))
            source_uri = source_uri_fn(p) if source_uri_fn else str(p)
            v = decide(findings, metrics, image_sha256=sha,
                       policy_version=self.policy_version,
                       analyzer_version=self.analyzer_version,
                       source_uri=source_uri)
            if img is None:
                counts["decode_fail"] += 1
            self.store.record(image_sha256=sha, verdict=v.verdict,
                              findings=findings, metrics=metrics,
                              policy_version=v.policy_version,
                              analyzer_version=v.analyzer_version,
                              source_uri=source_uri)
            counts[v.verdict] += 1
            per_image.append({"path": str(p), "sha256": sha,
                              "verdict": v.verdict,
                              "reasons": list(v.reasons),
                              "quality_tags": list(v.quality_tags)})

        total = sum(counts[k] for k in
                    ("accept", "warn", "manual_review", "reject"))
        summary = {
            "policy_version": self.policy_version,
            "analyzer_version": self.analyzer_version,
            "counts": counts,
            "processed": total,
            "ratios": ({k: round(counts[k] / total, 4) for k in
                        ("accept", "warn", "manual_review", "reject")}
                       if total else {}),
            "per_image": per_image,
        }
        return summary

    def write_report(self, summary: dict, report_path) -> None:
        _atomic_write_json(Path(report_path), summary)
