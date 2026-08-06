"""VLM-008：训练/验证划分防泄漏守卫（fail-closed，禁止随机 9:1）。

隔离维度：SHA、near_dup_group、customer、store、session、package_version；
frozen 与 active protocol 样本不得进入 train。任何违规 → SplitLeakageError
并附可审计违规清单。
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

GROUP_KEYS = ("customer", "store", "session", "near_dup_group",
              "package_version")


class SplitLeakageError(Exception):
    """划分泄漏（fail-closed）。violations 为可审计违规清单。"""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = list(violations)
        super().__init__("split leakage: " + "; ".join(self.violations[:8])
                         + (f"（共 {len(self.violations)} 项）"
                            if len(self.violations) > 8 else ""))


def _group_value(record: Mapping, key: str):
    if key == "sha256":
        return record.get("sha256")
    return (record.get("split_group") or {}).get(key)


def validate_splits(records: Iterable[Mapping]) -> None:
    """校验清单（每条含 sample_id/split/sha256/split_group/frozen/
    active_protocol），任何跨 split 的组值重叠或 train 中的 frozen/
    active protocol 样本都会抛出 SplitLeakageError。"""
    violations: list[str] = []
    seen: dict[str, dict[object, set[str]]] = {
        key: {} for key in ("sha256", *GROUP_KEYS)
    }
    for rec in records:
        split = rec.get("split")
        sid = rec.get("sample_id", "?")
        if split == "train" and rec.get("frozen"):
            violations.append(f"frozen sample in train: {sid}")
        if split == "train" and rec.get("active_protocol"):
            violations.append(f"active_protocol sample in train: {sid}")
        for key, table in seen.items():
            value = _group_value(rec, key)
            if value is None:
                violations.append(f"missing split key '{key}' on {sid}")
                continue
            splits = table.setdefault(value, set())
            splits.add(split)
            if len(splits) > 1:
                violations.append(
                    f"{key}={value} spans splits {sorted(splits)} (sample {sid})")
    if violations:
        raise SplitLeakageError(sorted(set(violations)))
