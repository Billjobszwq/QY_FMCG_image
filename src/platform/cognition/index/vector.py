"""向量端口（Task 8；R2-05 收口）。

Provider 协议（round-2-hardening/01 §6.1）：
provider_id / model_name / model_revision / dimension /
normalization_version / available / encode_documents / encode_queries。

embedding provider 不可用时明确 degraded，不返回假向量（05 Task 8 /
02 §8.2）。禁止哈希伪向量/随机向量/gold-set 特制映射冒充 dense；
测试 fake 只用于验证协议、身份与融合逻辑，不作为语义质量证据。
"""
from __future__ import annotations

import math
from typing import Any, Protocol


class VectorProvider(Protocol):
    provider_id: str
    model_name: str
    model_revision: str
    dimension: int
    normalization_version: str

    def available(self) -> bool: ...

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...

    def encode_queries(self, texts: list[str]) -> list[list[float]]: ...


class UnavailableVectorProvider:
    """显式不可用 provider：网关据此标记 degraded，而不是伪造向量。"""

    provider_id = "none"
    model_name = "unavailable"
    model_revision = ""
    dimension = 0
    normalization_version = ""

    def available(self) -> bool:
        return False

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("vector provider 不可用（不得调用）")

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("vector provider 不可用（不得调用）")


def provider_identity(provider: Any) -> dict[str, Any]:
    """规范化 provider 身份（索引 identity / mismatch 判定）。
    旧式 provider（仅 model_name/encode）以稳定缺省值表达。"""
    if provider is None:
        return {"provider_id": "none", "model_name": "",
                "model_revision": "", "dimension": 0,
                "normalization_version": ""}
    return {"provider_id": getattr(provider, "provider_id", "legacy"),
            "model_name": getattr(provider, "model_name", "unknown"),
            "model_revision": getattr(provider, "model_revision", ""),
            "dimension": int(getattr(provider, "dimension", 0) or 0),
            "normalization_version": getattr(
                provider, "normalization_version", "")}


def identity_string(provider: Any) -> str:
    """不可包含任何凭据；仅身份字段。"""
    d = provider_identity(provider)
    return (f"{d['provider_id']}/{d['model_name']}"
            f"@{d['model_revision']}:dim={d['dimension']}"
            f":norm={d['normalization_version']}")


def encode_documents(provider: Any, texts: list[str]) -> list[list[float]]:
    """协议兼容编码：优先 encode_documents，回退旧式 encode。"""
    fn = getattr(provider, "encode_documents", None)
    if fn is None:
        fn = provider.encode
    return fn(texts)


def encode_queries(provider: Any, texts: list[str]) -> list[list[float]]:
    fn = getattr(provider, "encode_queries", None)
    if fn is None:
        fn = getattr(provider, "encode_documents", None) or provider.encode
    return fn(texts)


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def dense_scores(query_vec: list[float],
                 chunk_vecs: list[dict[str, Any]],
                 allowed: set[str]) -> dict[str, float]:
    """chunk_vecs: [{chunk_id, vector}]；只对 allowed 计分。"""
    out: dict[str, float] = {}
    for cv in chunk_vecs:
        if cv["chunk_id"] not in allowed:
            continue
        out[cv["chunk_id"]] = cosine(query_vec, cv["vector"])
    return out
