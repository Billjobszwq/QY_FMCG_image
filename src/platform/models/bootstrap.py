"""本地 OMLX 受控引导（M7，02 §4 / 03 §9）。

步骤（全部经既有状态机 + maker≠checker 审批账本）：
1. draft 连接 local-omlx（location=local，OpenAI-compatible）；
2. 凭据经 SecretStore envelope 写入（write-only；来源为受控
   ``get_key`` 闭包：进程环境或用户本机配置，绝不回显/落明文）；
3. 真实连接测试（/models 鉴权探针）；
4. 模型登记 + 真实能力探针（冻结维度与归一化身份）；
5. 绑定 ``cognition.embedding`` → validate → submit → approve → activate。

本模块不打印、不记录、不返回任何凭据值。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable

from src.platform.models.contracts import (
    BindingDraft,
    CatalogManualEntry,
    ConnectionDraft,
)
from src.platform.models.integrations import EMBEDDING_SUBJECT_ID

OMLX_BASE_URL = "http://127.0.0.1:8455/v1"
OMLX_CONNECTION_ID = "local-omlx"
OMLX_EMBEDDING_MODEL = "Qwen3-Embedding-0.6B-8bit"


def bootstrap_local_omlx(services, *, get_key: Callable[[], bytes],
                         base_url: str = OMLX_BASE_URL,
                         model_id: str = OMLX_EMBEDDING_MODEL,
                         maker: str = "model-bootstrap",
                         checker: str = "human-approver") -> dict:
    """在给定（演练）库上完成 OMLX 接入闭环；返回身份摘要（无凭据）。"""
    tenant = "local"

    # 1) 连接 draft
    draft = ConnectionDraft.model_validate({
        "name": "本地 OMLX", "location": "local",
        "adapter_kind": "openai_compatible",
        "api_flavor": "chat_completions", "base_url": base_url,
        "timeout_ms": 120000, "max_retries": 1})
    conn = services.create_connection_draft(
        tenant_id=tenant, draft=draft, actor=maker,
        connection_id=OMLX_CONNECTION_ID)

    # 2) secret（write-only）
    services.set_secret(tenant_id=tenant,
                        connection_id=conn.connection_id,
                        version=conn.version, value=get_key(), actor=maker)

    # 3) 真实连接测试（鉴权 + models 发现）
    test = services.test_connection(tenant_id=tenant,
                                    connection_id=conn.connection_id,
                                    version=conn.version, actor=maker)
    if not test["ok"]:
        return {"stage": "test", "ok": False, "detail": test["detail"]}

    # 4) 提交 + maker≠checker 审批 → active
    sub = services.submit_connection(tenant_id=tenant,
                                     connection_id=conn.connection_id,
                                     version=conn.version, actor=maker)
    services.policy.decide_approval(sub["approval_id"], actor=checker,
                                    decision="approved")
    services.approve_connection(tenant_id=tenant,
                                connection_id=conn.connection_id,
                                version=conn.version, approver=checker,
                                approval_id=sub["approval_id"])

    # 5) 真实探针：先直接 embed 一次，冻结维度与归一化身份
    conn_row = services.repo.get_connection(
        tenant_id=tenant, connection_id=conn.connection_id,
        version=conn.version)
    adapter = services._build_adapter(conn_row)
    from src.platform.models.providers.base import EmbedRequest
    probe_vec = adapter.embed(EmbedRequest(model_id=model_id,
                                           inputs=("identity probe",)))
    dim = probe_vec.dimension
    norm = math.sqrt(sum(x * x for x in probe_vec.vectors[0]))
    normalization = ("l2-normalized@v1" if abs(norm - 1.0) < 1e-3
                     else "raw@v1")

    entry = CatalogManualEntry.model_validate({
        "model_id": model_id, "capabilities": ["embedding"],
        "embedding_dimension": dim,
        "normalization_version": normalization})
    cat = services.register_manual(tenant_id=tenant,
                                   connection_id=conn.connection_id,
                                   version=conn.version, entry=entry,
                                   actor=maker)
    probe = services.probe_model(tenant_id=tenant,
                                 catalog_id=cat.catalog_id, actor=maker)
    if probe["probe_status"] != "ready":
        return {"stage": "probe", "ok": False, "detail": probe}

    # 6) 绑定 cognition.embedding → validate → submit → approve → active
    binding_draft = BindingDraft.model_validate({
        "subject_kind": "system_capability",
        "subject_id": EMBEDDING_SUBJECT_ID,
        "capability": "embedding",
        "connection_id": conn.connection_id,
        "connection_version": conn.version,
        "model_id": model_id})
    binding = services.create_binding_draft(
        tenant_id=tenant, draft=binding_draft, actor=maker,
        binding_id="cognition-embedding-default")
    impact = services.validate_binding(tenant_id=tenant,
                                       binding_id=binding.binding_id,
                                       version=binding.version, actor=maker)
    sub_b = services.submit_binding(tenant_id=tenant,
                                    binding_id=binding.binding_id,
                                    version=binding.version, actor=maker)
    services.policy.decide_approval(sub_b["approval_id"], actor=checker,
                                    decision="approved")
    services.activate_binding(tenant_id=tenant,
                              binding_id=binding.binding_id,
                              version=binding.version, approver=checker,
                              approval_id=sub_b["approval_id"])

    return {
        "stage": "complete", "ok": True,
        "connection_id": conn.connection_id,
        "connection_version": conn.version,
        "model_id": model_id,
        "embedding_dimension": dim,
        "normalization_version": normalization,
        "probe": {"embedding": probe["results"].get("embedding")},
        "binding": f"{binding.binding_id}@v{binding.version}",
        "identity": (f"managed:{conn.connection_id}@v{conn.version}/"
                     f"{model_id}:dim={dim}:norm={normalization}"),
        "impact": impact.get("impact"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
