"""L1→L2 candidate 生成的确定性契约（Task 6）。

source_hash 是幂等键的一半：同一 (task_id, 排序后的 l1_ids) 永远得到
同一 hash；与 consolidator_version 组成 UNIQUE，保证重放 Consolidate
不产生重复 candidate（冲突版本并存而非静默覆盖，见 02 §4.2）。
"""
from __future__ import annotations

import hashlib
import json


def source_hash(task_id: str, l1_ids: list[str]) -> str:
    payload = json.dumps({"task_id": task_id, "l1_ids": sorted(l1_ids)},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
