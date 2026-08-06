"""VLM-006：SKU 候选召回适配器（S3：OCR/属性/向量）。

红线：
- 返回闭集 CandidateSet：所有候选必须来自 SKU Registry，
  闭集外候选一律过滤，registry 为空/后端缺失 fail-closed；
- registry_version 与 retrieval_version 必填（审计/证据链）。
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from src.modules.fmcg.adapters import CapabilityAdapterError
from src.modules.fmcg.cascade.contracts import Candidate, CandidateSet
from src.modules.fmcg.cascade.manifest import CAP_RETRIEVE

RETRIEVAL_VERSION_DEFAULT = "retrieval.v1"


class SkuRetrievalAdapter:
    capability_id = CAP_RETRIEVE

    def __init__(
        self,
        *,
        registry_ids: Iterable[str],
        backend: Callable[[str], list[tuple[str, float]]] | None = None,
        registry_version: str,
        retrieval_version: str = RETRIEVAL_VERSION_DEFAULT,
    ) -> None:
        self._ids = set(registry_ids)
        self._backend = backend
        self._registry_version = registry_version
        self._retrieval_version = retrieval_version

    def retrieve(self, *, region_id: str, limit: int = 8) -> CandidateSet:
        if not self._ids:
            raise CapabilityAdapterError("SKU Registry 为空，召回 fail-closed")
        if self._backend is None:
            raise CapabilityAdapterError("召回后端未注入，fail-closed")
        try:
            raw = self._backend(region_id) or []
        except Exception as e:
            raise CapabilityAdapterError(f"候选召回失败: {e}") from e
        candidates = [
            Candidate(sku_id=str(sku_id), score=float(score))
            for sku_id, score in raw
            if sku_id in self._ids
        ][: max(1, int(limit))]
        return CandidateSet(
            candidate_set_id=f"cs-{region_id}",
            region_id=region_id,
            registry_version=self._registry_version,
            retrieval_version=self._retrieval_version,
            candidates=candidates,
        )
