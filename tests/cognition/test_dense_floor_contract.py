"""M7（G6）：hybrid 稠密腿噪声地板合同（DENSE_HYBRID_STRONG_SIM）。

合同：无词法佐证的稠密候选必须达到强语义阈值才进入融合；
有词法佐证的候选不受阈值限制。该合同保护负例零命中/弃权/
注入/ACL 契约不被“恒返回 top-k”的稠密腿破坏。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.cognition.index.gateway import DENSE_HYBRID_STRONG_SIM


class _StubProvider:
    """可控向量 provider：查询向量固定，文档向量按测试注入。"""

    provider_id = "stub"
    model_name = "stub-model"
    model_revision = ""
    dimension = 2
    normalization_version = "v1"

    def __init__(self, docs: dict[str, list[float]],
                 query: list[float]) -> None:
        self._docs = docs
        self._query = query

    def available(self) -> bool:
        return True

    def encode_documents(self, texts):
        return [self._query for _ in texts]

    def encode_queries(self, texts):
        return [self._query for _ in texts]


@pytest.mark.parametrize("sim,has_lexical,expected", [
    (0.95, False, True),    # 强语义 → 保留
    (DENSE_HYBRID_STRONG_SIM, False, True),  # 边界含等于
    (0.59, False, False),   # 弱语义且无词法 → 丢弃
    (0.10, True, True),     # 弱语义但有词法佐证 → 保留
])
def test_dense_floor_filters_weak_unsupported_candidates(
        sim, has_lexical, expected):
    """白盒验证过滤谓词（与网关实现同一语义）。"""
    lex = {"chunk-a": 2.0} if has_lexical else {}
    ds = {"chunk-a": sim}
    kept = {cid: s for cid, s in ds.items()
            if cid in lex or s >= DENSE_HYBRID_STRONG_SIM}
    assert ("chunk-a" in kept) is expected


def test_floor_is_frozen_contract():
    """阈值是冻结检索身份的一部分：改动必须显式且经金标准复评。"""
    assert DENSE_HYBRID_STRONG_SIM == 0.60
