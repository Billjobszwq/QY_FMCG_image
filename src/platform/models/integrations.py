"""统一模型管理 → 认知索引的受控桥接（M7）。

纪律：
- Build 与 Query 使用同一个受管 Provider 实例/身份（同一 Binding Identity
  冻结）；身份不符由既有索引目录/网关 fail-closed。
- 无受管绑定时返回 None，调用方退回 ``provider_from_env``
  （source=legacy_env，迁移期回退，必须可观测）。
- 凭据只在 Adapter 的短租约闭包内出现；identity 不含凭据。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.platform.models.contracts import ResolveRequest
from src.platform.models.providers.base import EmbedRequest

EMBEDDING_SUBJECT_ID = "cognition.embedding"


class ManagedVectorProvider:
    """VectorProvider 适配器：把统一 Adapter 暴露给认知索引端口。"""

    def __init__(self, adapter: Any, *, connection_id: str,
                 connection_version: int, model_id: str,
                 model_revision: str, dimension: int,
                 normalization_version: str) -> None:
        self._adapter = adapter
        self.provider_id = f"managed:{connection_id}@v{connection_version}"
        self.model_name = model_id
        self.model_revision = model_revision
        self.dimension = int(dimension)
        self.normalization_version = normalization_version

    def available(self) -> bool:
        return True

    def __repr__(self) -> str:
        return (f"ManagedVectorProvider(provider_id={self.provider_id!r},"
                f" model={self.model_name!r}, dim={self.dimension})")

    def _encode(self, texts: list[str]) -> list[list[float]]:
        result = self._adapter.embed(EmbedRequest(
            model_id=self.model_name, inputs=tuple(texts)))
        if len(result.vectors) != len(texts):
            raise RuntimeError(
                f"embedding 数量不一致: {len(result.vectors)} !="
                f" {len(texts)}")
        if self.dimension and result.dimension != self.dimension:
            raise RuntimeError(
                f"embedding 维度不符: 绑定 {self.dimension},"
                f" 返回 {result.dimension}")
        return [list(v) for v in result.vectors]

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(list(texts))

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode(list(texts))


def agent_definition_lookup_factory(agent_runtime, repo,
                                    tenant_id: str = "local"):
    """Resolver 的 Agent 事实源钩子：published Agent Definition 优先。

    请求 subject 形如 ``module:agent:<agent_id>`` 时，从 published
    Definition 的 ``provider=connection:<id>@v<N>`` 受管引用返回身份；
    未配置受管引用 → None（由绑定/回退链接管）。
    """

    def lookup(req):
        subject = req.subject_id or ""
        if not subject.startswith("agent:"):
            return None
        agent_id = subject[len("agent:"):]
        defn = agent_runtime.get_published_definition(agent_id)
        if defn is None:
            return None
        provider = str(defn.get("provider") or "")
        if not provider.startswith("connection:"):
            return None
        ref = provider[len("connection:"):]
        conn_id, _, vtxt = ref.partition("@v")
        try:
            version = int(vtxt)
        except ValueError:
            return None
        conn = repo.get_connection(tenant_id=tenant_id,
                                   connection_id=conn_id, version=version)
        if conn is None or conn.status != "active":
            return None
        return {"connection_id": conn_id, "connection_version": version,
                "adapter_kind": conn.adapter_kind,
                "location": conn.location,
                "model_id": str(defn.get("model") or ""),
                "model_revision": "",
                "embedding_dimension": None,
                "normalization_version": None,
                "binding_id": "", "binding_version": 0}

    return lookup


class MeteredEmbedAdapter:
    """计量包装：每次真实 embed 落调用账本并结算诚实单位（03 §9）。"""

    def __init__(self, adapter: Any, metering: Any, ctx_kwargs: dict,
                 reserved_output_tokens: float = 0.0) -> None:
        self._adapter = adapter
        self._metering = metering
        self._ctx_kwargs = ctx_kwargs

    def __getattr__(self, name):
        return getattr(self._adapter, name)

    def embed(self, request):
        from src.platform.models.metering import CallContext, Settlement
        ctx = CallContext(**self._ctx_kwargs)
        call_id = self._metering.begin_call(ctx)
        try:
            result = self._adapter.embed(request)
        except Exception as e:
            self._metering.settle_call(call_id, Settlement(
                ok=False, error_code=getattr(e, "code", "MODEL_ERROR"),
                meter_source="platform_observed"))
            raise
        self._metering.settle_call(call_id, Settlement(
            ok=True,
            embedding_inputs=len(request.inputs),
            embedding_vectors=len(result.vectors),
            compute_ms=result.latency_ms,
            input_tokens=result.usage.input_tokens
            if result.usage_complete else None,
            meter_source=("provider_reported"
                          if result.usage_complete
                          else "platform_observed"),
            provider_request_id=result.provider_request_id))
        return result


def resolve_embedding_provider(services, *, principal_id: str,
                               tenant_id: str = "local",
                               customer_id: str = "",
                               project_id: str = ""
                               ) -> ManagedVectorProvider | None:
    """按当前绑定解析受管 embedding provider；无受管绑定 → None。

    fail-closed：disabled/未 probe/身份不全的绑定由 Resolver 过滤，
    这里不兜底伪造。
    """
    req = ResolveRequest.model_validate({
        "principal_id": principal_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "project_id": project_id,
        "subject_kind": "system_capability",
        "subject_id": EMBEDDING_SUBJECT_ID,
        "capability": "embedding",
        "as_of": datetime.now(timezone.utc).isoformat(),
    })
    resolved = services.resolver.resolve(req)
    if resolved is None or resolved.source != "managed":
        return None
    conn = services.repo.get_connection(
        tenant_id=tenant_id, connection_id=resolved.connection_id,
        version=resolved.connection_version)
    if conn is None:
        return None
    adapter = services._build_adapter(conn)
    metering = getattr(services, "metering", None)
    if metering is not None:
        adapter = MeteredEmbedAdapter(adapter, metering, {
            "tenant_id": tenant_id,
            "principal_id": principal_id,
            "principal_kind": "service_account",
            "customer_id": customer_id,
            "project_id": project_id,
            "module": "cognition",
            "capability": "embedding",
            "connection_id": resolved.connection_id,
            "connection_version": resolved.connection_version,
            "binding_id": resolved.binding_id,
            "binding_version": resolved.binding_version,
            "model_id": resolved.model_id,
            "model_revision": resolved.model_revision,
        })
    return ManagedVectorProvider(
        adapter, connection_id=resolved.connection_id,
        connection_version=resolved.connection_version,
        model_id=resolved.model_id,
        model_revision=resolved.model_revision,
        dimension=resolved.embedding_dimension or 0,
        normalization_version=resolved.normalization_version or "v1")
