"""N2 Task 5：SKU/unknown/new packaging 身份治理（02 设计 §5/红线 6）。

- 208 Registry 冻结 + alias 版本（内容 hash）；
- other/百事other/可乐other 分层为 unknown/brand_unknown/category_unknown，
  绝不强映射到已有 208 类；
- 具体未映射名称 → alias_pending（人工裁决），禁猜映射；
- 数据集与识别结果一律存 canonical sku_id，不用显示名做等值判断。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

UNKNOWN_TIERS = {
    "other": "unknown",
    "百事other": "brand_unknown",
    "可乐other": "category_unknown",
}


class IdentityError(RuntimeError):
    """身份治理错误（fail-closed）。"""


class SkuIdentityService:
    def __init__(self, *, registry_path: Path | str,
                 aliases_path: Path | str | None = None) -> None:
        self._registry = json.loads(
            Path(registry_path).read_text(encoding="utf-8"))
        if len(self._registry) != 208:
            raise IdentityError(
                f"Registry 冻结校验失败：期望 208，实际 {len(self._registry)}")
        self._by_name = {name: v["sku_id"]
                         for name, v in self._registry.items()}
        self._alias_index: dict[str, str] = {}
        if aliases_path is not None and Path(aliases_path).exists():
            doc = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
            for c in doc.get("canonicals", []):
                folder = c.get("kb_folder", "")
                # kb_folder 与其登记别名都指向同一 canonical：
                # 经 registry 显示名回查 sku_id
                target = None
                for a in c.get("aliases", []):
                    if a in self._by_name:
                        target = self._by_name[a]
                        break
                if target is None:
                    continue
                if folder:
                    self._alias_index[folder] = target
                for a in c.get("aliases", []):
                    self._alias_index.setdefault(a, target)
        self._version = hashlib.sha256(
            json.dumps(self._registry, sort_keys=True,
                       ensure_ascii=False).encode()).hexdigest()[:16]

    def registry_size(self) -> int:
        return len(self._registry)

    def version(self) -> str:
        return f"sku_registry@{self._version}"

    def resolve(self, name: str, *, code: str | None = None
                ) -> dict[str, Any]:
        """点名称 → canonical 身份。绝不猜映射。"""
        name = (name or "").strip()
        if code and str(code).startswith("ADM") and name in self._by_name:
            return {"sku_id": self._by_name[name], "status": "mapped",
                    "via": "code+name"}
        if name in self._by_name:
            return {"sku_id": self._by_name[name], "status": "mapped",
                    "via": "registry_name"}
        if name in self._alias_index:
            return {"sku_id": self._alias_index[name], "status": "mapped",
                    "via": "alias"}
        tier = UNKNOWN_TIERS.get(name)
        if tier is not None:
            return {"sku_id": None, "status": tier, "via": "unknown_tier"}
        if name.endswith("other"):
            return {"sku_id": None, "status": "brand_unknown",
                    "via": "unknown_tier_rule"}
        if not name or name in ("None", "none"):
            return {"sku_id": None, "status": "unknown",
                    "via": "empty_name"}
        # 具体但未登记名称：等待人工 alias/new SKU 裁决，禁猜映射
        return {"sku_id": None, "status": "alias_pending",
                "via": "pending_human_adjudication"}

    def map_points(self, points: list[dict[str, Any]]) -> dict[str, Any]:
        rep = {"total": len(points), "mapped": 0, "unknown": 0,
               "brand_unknown": 0, "category_unknown": 0,
               "alias_pending": 0, "pending_names": {}}
        for p in points:
            out = self.resolve(str(p.get("name") or ""),
                               code=p.get("code"))
            st = out["status"]
            if st in rep:
                rep[st] += 1
            if st == "alias_pending":
                rep["pending_names"][str(p.get("name"))] = \
                    rep["pending_names"].get(str(p.get("name")), 0) + 1
        return rep
