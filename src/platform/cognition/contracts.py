"""认知内核 typed contracts（02-DATA-CONTRACTS §2/§6/§7）。

全部契约：
- frozen dataclass；构造时 fail-closed 校验；
- to_dict/from_dict 严格 round-trip，未知字段拒绝；
- content_hash：canonical JSON（sort_keys）的 sha256，字段顺序无关。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import MISSING, dataclass, fields
from typing import Any, Mapping

from .errors import CognitionValidationError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

TARGET_KINDS = ("knowledge", "memory_l2", "memory_l3", "skill", "external")
QUERY_MODES = ("lookup", "case_analysis", "methodology", "deep_research")
CLAIM_TYPES = ("fact", "inference", "recommendation", "unknown")
CLAIM_IMPORTANCE = ("low", "medium", "high")
SUPPORT_STATUSES = ("supported", "partially_supported", "contradicted",
                    "unsupported")
BUILD_STATUSES = ("building", "ready", "failed", "revoked")
INDEX_TARGET_KINDS = ("knowledge", "memory_l2", "memory_l3", "skill")


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8"))\
        .hexdigest()


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_float(v: Any) -> bool:
    return isinstance(v, float) and not isinstance(v, bool)


def _str_seq(name: str, cls: type, v: Any) -> tuple[str, ...]:
    """集合型字符串序列：拒绝裸字符串（防逐字符拆散），排序保证
    hash 稳定（顺序无语义的字段）。"""
    if isinstance(v, str) or not isinstance(v, (list, tuple)):
        raise CognitionValidationError(
            f"{cls.__name__}: {name} 必须为字符串序列")
    for item in v:
        if not isinstance(item, str) or not item:
            raise CognitionValidationError(
                f"{cls.__name__}: {name} 元素必须为非空字符串")
    return tuple(sorted(v))


def _strict(cls: type, data: Mapping[str, Any]) -> dict[str, Any]:
    """拒绝未知字段与缺失必填字段（fail-closed），返回纯 dict。"""
    if not isinstance(data, Mapping):
        raise CognitionValidationError(f"{cls.__name__} 需要 object")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise CognitionValidationError(
            f"{cls.__name__} 未知字段: {unknown}")
    required = {f.name for f in fields(cls)
                if f.default is MISSING and f.default_factory is MISSING}
    missing = sorted(required - set(data))
    if missing:
        raise CognitionValidationError(
            f"{cls.__name__} 缺失字段: {missing}")
    return dict(data)


def _build(cls: type, d: dict[str, Any]) -> Any:
    """构造包装：任何类型/值错误都归一为 CognitionValidationError。"""
    try:
        return cls(**d)
    except CognitionValidationError:
        raise
    except (TypeError, ValueError) as e:
        raise CognitionValidationError(
            f"{cls.__name__} 构造失败: {e}") from e


def _require(cond: bool, cls: type, msg: str) -> None:
    if not cond:
        raise CognitionValidationError(f"{cls.__name__}: {msg}")


class _Contract:
    """to_dict/from_dict/content_hash 公共实现。"""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            v = getattr(self, f.name)
            if isinstance(v, tuple):
                v = list(v)
            out[f.name] = v
        return out

    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def hash_of(cls, data: Mapping[str, Any]) -> str:
        return canonical_hash(data)


@dataclass(frozen=True)
class CognitiveQueryRequest(_Contract):
    """统一查询请求（02 §7）。filters 仅允许结构化键值，不接受 SQL。"""

    query: str
    target_kinds: tuple[str, ...]
    mode: str
    top_k: int = 8
    filters: Mapping[str, Any] | None = None
    include_history: bool = False
    require_citations: bool = True

    def __post_init__(self) -> None:
        cls = type(self)
        _require(isinstance(self.query, str) and self.query.strip(),
                 cls, "query 必填")
        _require(len(self.query) <= 4000, cls, "query 过长")
        kinds = _str_seq("target_kinds", cls, self.target_kinds)
        _require(len(kinds) > 0, cls, "target_kinds 必填")
        bad = sorted(set(kinds) - set(TARGET_KINDS))
        _require(not bad, cls, f"非法 target_kinds: {bad}")
        object.__setattr__(self, "target_kinds", kinds)
        _require(self.mode in QUERY_MODES, cls,
                 f"mode 必须为 {QUERY_MODES}")
        _require(_is_int(self.top_k) and 1 <= self.top_k <= 100,
                 cls, "top_k 必须为 1..100 的整数")
        if self.filters is not None:
            _require(isinstance(self.filters, Mapping), cls,
                     "filters 必须为 object")
        object.__setattr__(self, "filters",
                           dict(self.filters or {}))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CognitiveQueryRequest":
        d = _strict(cls, data)
        d["target_kinds"] = list(d.get("target_kinds") or [])
        return _build(cls, d)


@dataclass(frozen=True)
class ArtifactRef(_Contract):
    """CAS 不可变工件引用（02 §8.3）。"""

    artifact_ref: str
    sha256: str
    size_bytes: int
    media_type: str
    producer_run: str
    retention: str

    def __post_init__(self) -> None:
        cls = type(self)
        _require(bool(self.artifact_ref), cls, "artifact_ref 必填")
        _require(bool(_SHA256_RE.match(self.sha256 or "")), cls,
                 "sha256 必须为 64 位十六进制")
        _require(_is_int(self.size_bytes) and self.size_bytes >= 0,
                 cls, "size_bytes 非法")
        _require(bool(self.media_type), cls, "media_type 必填")
        # 02 §8.3：ArtifactRef 必须记录 producer run 与 retention
        _require(bool(self.producer_run), cls, "producer_run 必填")
        _require(bool(self.retention), cls, "retention 必填")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRef":
        return _build(cls, _strict(cls, data))


@dataclass(frozen=True)
class EvidenceSpan(_Contract):
    """可定位证据片段（02 §2；quote 必须能回到 chunk/locator）。"""

    span_id: str
    chunk_id: str
    quote_start: int
    quote_end: int
    quote_hash: str
    normalized_quote: str
    locator: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        cls = type(self)
        _require(bool(self.span_id) and bool(self.chunk_id), cls,
                 "span_id/chunk_id 必填")
        _require(_is_int(self.quote_start) and self.quote_start >= 0,
                 cls, "quote_start 非法")
        _require(_is_int(self.quote_end)
                 and self.quote_end > self.quote_start, cls,
                 "quote_end 必须大于 quote_start")
        _require(bool(_SHA256_RE.match(self.quote_hash or "")), cls,
                 "quote_hash 必须为 64 位十六进制")
        object.__setattr__(self, "locator", dict(self.locator or {}))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceSpan":
        return _build(cls, _strict(cls, data))


@dataclass(frozen=True)
class Claim(_Contract):
    """研究 Claim（02 §6 research_claim；fact/inference/recommendation/
    unknown）。research_run_id 必填：Claim 必须可回链所属研究运行。"""

    claim_id: str
    research_run_id: str
    text: str
    claim_type: str
    importance: str
    support_status: str
    confidence: float

    def __post_init__(self) -> None:
        cls = type(self)
        _require(bool(self.claim_id) and bool(self.text), cls,
                 "claim_id/text 必填")
        _require(bool(self.research_run_id), cls,
                 "research_run_id 必填（Claim 必须回链研究运行）")
        _require(self.claim_type in CLAIM_TYPES, cls,
                 f"claim_type 必须为 {CLAIM_TYPES}")
        _require(self.importance in CLAIM_IMPORTANCE, cls,
                 f"importance 必须为 {CLAIM_IMPORTANCE}")
        _require(self.support_status in SUPPORT_STATUSES, cls,
                 f"support_status 必须为 {SUPPORT_STATUSES}")
        _require((_is_float(self.confidence) or _is_int(self.confidence))
                 and 0.0 <= self.confidence <= 1.0, cls,
                 "confidence 必须为 0..1 的数值")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Claim":
        return _build(cls, _strict(cls, data))


@dataclass(frozen=True)
class IndexSnapshot(_Contract):
    """索引构建快照（03 §3.2；索引是可重建派生物）。"""

    index_snapshot_id: str
    target_kind: str
    corpus_snapshot_id: str
    backend: str
    embedding_model: str | None
    reranker_model: str | None
    analyzer_version: str
    chunk_policy_version: str
    parameters: Mapping[str, Any] | None
    item_count: int
    source_manifest_hash: str
    build_status: str
    quality_report_ref: str

    def __post_init__(self) -> None:
        cls = type(self)
        _require(bool(self.index_snapshot_id), cls,
                 "index_snapshot_id 必填")
        _require(self.target_kind in INDEX_TARGET_KINDS, cls,
                 f"target_kind 必须为 {INDEX_TARGET_KINDS}")
        _require(bool(self.corpus_snapshot_id), cls,
                 "corpus_snapshot_id 必填")
        _require(bool(self.backend), cls, "backend 必填")
        _require(self.build_status in BUILD_STATUSES, cls,
                 f"build_status 必须为 {BUILD_STATUSES}")
        _require(bool(_SHA256_RE.match(self.source_manifest_hash or "")),
                 cls, "source_manifest_hash 必须为 64 位十六进制")
        _require(_is_int(self.item_count) and self.item_count >= 0,
                 cls, "item_count 非法")
        object.__setattr__(self, "parameters", dict(self.parameters or {}))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IndexSnapshot":
        return _build(cls, _strict(cls, data))


@dataclass(frozen=True)
class RetrievalCandidate(_Contract):
    """检索候选指针（默认只返回摘要与指针，不返回全文）。"""

    target_kind: str
    target_id: str
    version: str
    score_breakdown: Mapping[str, Any] | None = None
    summary: str = ""
    spans: tuple[EvidenceSpan, ...] = ()
    index_snapshot_id: str = ""

    def __post_init__(self) -> None:
        cls = type(self)
        _require(self.target_kind in TARGET_KINDS, cls,
                 f"target_kind 必须为 {TARGET_KINDS}")
        _require(bool(self.target_id), cls, "target_id 必填")
        object.__setattr__(self, "score_breakdown",
                           dict(self.score_breakdown or {}))
        object.__setattr__(self, "spans", tuple(self.spans or ()))

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["spans"] = [s.to_dict() for s in self.spans]
        return d

    @classmethod
    def from_dict(cls,
                  data: Mapping[str, Any]) -> "RetrievalCandidate":
        d = _strict(cls, data)
        d["spans"] = [EvidenceSpan.from_dict(s)
                      for s in d.get("spans") or ()]
        return _build(cls, d)


@dataclass(frozen=True)
class SearchResult(_Contract):
    """统一查询结果（02 §7：候选指针 + 权限决策摘要 + trace）。"""

    query: str
    candidates: tuple[RetrievalCandidate, ...]
    degraded: bool
    index_snapshot_ids: tuple[str, ...]
    policy_decision: Mapping[str, Any] | None = None
    retrieval_trace: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates",
                           tuple(self.candidates or ()))
        object.__setattr__(
            self, "index_snapshot_ids",
            _str_seq("index_snapshot_ids", type(self),
                     self.index_snapshot_ids))
        object.__setattr__(self, "policy_decision",
                           dict(self.policy_decision or {}))
        object.__setattr__(self, "retrieval_trace",
                           dict(self.retrieval_trace or {}))

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["candidates"] = [c.to_dict() for c in self.candidates]
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchResult":
        d = _strict(cls, data)
        d["candidates"] = [RetrievalCandidate.from_dict(c)
                           for c in d.get("candidates") or ()]
        d["index_snapshot_ids"] = list(d.get("index_snapshot_ids") or [])
        return _build(cls, d)
