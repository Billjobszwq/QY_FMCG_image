"""VLM-007：qwen3-vl:4b 闭集重排 HTTP 适配器（MLX-VLM OpenAI 兼容端点）。

红线（计划 §Task 7）：
- 只接受受控 base_url（http/https）、模型 ID 与 adapter revision；
- prompt 由固定模板构建，忽略 context 中一切注入键（如 system_prompt）；
- 输出必须经 QwenSkuDecision 校验；非法 JSON / 空响应 → needs_review，不伪造结论；
- accepted 的 SKU 必须位于候选闭集内，否则 needs_review + sku_outside_candidate_set；
- registry_version 缺失 fail-closed（不发起任何请求）;
- 超时/429/503 可重试（次数由策略注入）；其他 4xx 不重试；
- 调用前向 ModelResidencyManager 获取租约（busy 直接拒绝），finally 释放。

真实前向被训练门禁阻断：本模块不加载任何权重，HTTP 传输可注入（测试用 fake）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from src.modules.fmcg.cascade.contracts import Candidate, QwenSkuDecision
from src.modules.fmcg.cascade.manifest import CAP_QWEN

ADAPTER_REVISION_DEFAULT = "qwen3vl-adapter.v1"
SCHEMA_VERSION = "qwen-sku-decision.v1"

_RETRYABLE_STATUS = (429, 503)
_RETRYABLE_EXCEPTIONS = (TimeoutError, ConnectionError, OSError)

_SYSTEM_PROMPT = (
    "你是 SKU 闭集裁决器。只允许在给定候选列表内做裁决；"
    "输出必须是单个 JSON 对象，字段遵循 qwen-sku-decision.v1："
    "decision ∈ {accepted, unknown, same_sku_new_package, possible_new_sku, "
    "insufficient_evidence}；accepted 必须给出候选内 sku_id；"
    "禁止生成候选外的商品名或 SKU；证据不足时 abstain。"
)


class QwenAdapterError(Exception):
    """受控配置/输入错误（fail-closed，不发起请求）。"""


class QwenHttpError(Exception):
    """HTTP 层错误，携带状态码。"""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(f"HTTP {status_code}: {message}".strip())
        self.status_code = int(status_code)


class QwenTransportError(Exception):
    """最终传输失败（重试耗尽或不可重试）。"""


@dataclass(frozen=True)
class RerankResult:
    """适配器输出：级联决策词汇（accepted/needs_review/unknown/new_package）。

    raw 保留校验通过的 QwenSkuDecision（若存在），用于证据链。
    """

    decision: str
    sku_id: str | None = None
    package_version_id: str | None = None
    abstain_reason: str | None = None
    raw: QwenSkuDecision | None = None
    latency_ms: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


def _default_http_post(url: str, payload: dict, timeout: float) -> dict:
    """默认传输：标准库 urllib（无第三方依赖）。真实调用被门禁在外层阻断。"""
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise QwenHttpError(e.code, str(e.reason)) from e


class Qwen3VlMlxAdapter:
    capability_id = CAP_QWEN

    def __init__(
        self,
        *,
        base_url: str,
        model_id: str = "qwen3-vl:4b",
        adapter_revision: str = ADAPTER_REVISION_DEFAULT,
        http_post: Callable[[str, dict, float], dict] | None = None,
        residency: Any | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 1,
    ) -> None:
        if not isinstance(base_url, str) or not (
                base_url.startswith("http://") or base_url.startswith("https://")):
            raise QwenAdapterError(f"base_url 必须是受控 http(s) 地址: {base_url!r}")
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._adapter_revision = adapter_revision
        self._http_post = http_post or _default_http_post
        self._residency = residency
        self._timeout_s = float(timeout_s)
        self._max_retries = max(0, int(max_retries))

    # ---------- public ----------

    def rerank(
        self,
        context: dict[str, Any],
        *,
        candidates: Iterable[Candidate],
        run_id: str,
    ) -> RerankResult:
        registry_version = context.get("registry_version")
        if not registry_version:
            raise QwenAdapterError("context 缺少 registry_version，fail-closed")
        cands = list(candidates)
        if not cands:
            raise QwenAdapterError("候选集为空，fail-closed")

        lease = None
        if self._residency is not None:
            lease = self._residency.acquire("qwen3-vl:4b", run_id=run_id)
        try:
            return self._rerank_locked(context, cands, registry_version)
        finally:
            if lease is not None:
                self._residency.release(lease.lease_id)

    # ---------- internals ----------

    def _rerank_locked(
        self,
        context: dict[str, Any],
        cands: list[Candidate],
        registry_version: str,
    ) -> RerankResult:
        started = time.monotonic()
        payload = self._build_payload(context, cands, registry_version)
        url = f"{self._base_url}/v1/chat/completions"
        response = self._post_with_retry(url, payload)
        latency_ms = (time.monotonic() - started) * 1000.0
        usage = dict(response.get("usage") or {})
        content = self._extract_content(response)
        if not content.strip():
            return RerankResult("needs_review", abstain_reason="empty_response",
                                latency_ms=latency_ms, usage=usage)
        decision = self._parse_decision(content)
        if decision is None:
            return RerankResult("needs_review",
                                abstain_reason="invalid_model_output",
                                latency_ms=latency_ms, usage=usage)
        mapped = self._map_decision(decision, cands)
        return RerankResult(
            decision=mapped["decision"],
            sku_id=mapped["sku_id"],
            package_version_id=decision.package_version_id,
            abstain_reason=mapped["abstain_reason"],
            raw=decision,
            latency_ms=latency_ms,
            usage=usage,
        )

    def _build_payload(
        self,
        context: dict[str, Any],
        cands: list[Candidate],
        registry_version: str,
    ) -> dict[str, Any]:
        region = context.get("region") or {}
        # 固定模板：只注入受控字段，忽略 context 中的其他键（防注入）。
        user_text = json.dumps(
            {
                "task": "closed_set_sku_rerank",
                "registry_version": registry_version,
                "adapter_revision": self._adapter_revision,
                "region": {
                    "region_id": region.get("region_id"),
                    "box_px": list(region.get("box_px") or []),
                    "image_width": region.get("image_width"),
                    "image_height": region.get("image_height"),
                },
                "asset_sha": context.get("asset_sha"),
                "candidates": [
                    {"sku_id": c.sku_id, "score": c.score} for c in cands
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
        }

    def _post_with_retry(self, url: str, payload: dict) -> dict:
        attempts = self._max_retries + 1
        last_error: Exception | None = None
        for i in range(attempts):
            try:
                return self._http_post(url, payload, self._timeout_s)
            except QwenHttpError as e:
                if e.status_code not in _RETRYABLE_STATUS:
                    raise QwenTransportError(str(e)) from e
                last_error = e
            except _RETRYABLE_EXCEPTIONS as e:
                last_error = e
        raise QwenTransportError(
            f"传输失败（{attempts} 次尝试后）: {last_error}"
        ) from last_error

    @staticmethod
    def _extract_content(response: dict) -> str:
        try:
            return str(response["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _parse_decision(content: str) -> QwenSkuDecision | None:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None
        obj = dict(obj)
        obj.setdefault("schema_version", SCHEMA_VERSION)
        try:
            return QwenSkuDecision.model_validate(obj)
        except Exception:
            return None

    @staticmethod
    def _map_decision(
        decision: QwenSkuDecision, cands: list[Candidate]
    ) -> dict[str, Any]:
        allowed = {c.sku_id for c in cands}
        kind = decision.decision
        if kind == "accepted":
            if decision.sku_id in allowed:
                return {"decision": "accepted", "sku_id": decision.sku_id,
                        "abstain_reason": None}
            # 红线：候选外 SKU 永远不得 accepted。
            return {"decision": "needs_review", "sku_id": decision.sku_id,
                    "abstain_reason": "sku_outside_candidate_set"}
        if kind == "unknown":
            return {"decision": "unknown", "sku_id": None,
                    "abstain_reason": decision.abstain_reason or "unknown"}
        if kind in ("same_sku_new_package", "possible_new_sku"):
            return {"decision": "new_package", "sku_id": decision.sku_id,
                    "abstain_reason": None}
        # insufficient_evidence
        return {"decision": "needs_review", "sku_id": None,
                "abstain_reason": decision.abstain_reason or kind}
