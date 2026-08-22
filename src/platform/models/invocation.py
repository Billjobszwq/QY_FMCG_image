"""Agent/模块消费者的统一模型调用端口（M8）。

纪律（DEC-M004/M010）：
- Agent 模型事实源是 published Agent Definition：``provider`` 字段为
  受管引用 ``connection:<connection_id>@<version>``，``model`` 为模型 ID。
- 统一模型管理不保存第二份 Agent 绑定；这里只做聚合读取与调用。
- 旧环境变量（DEEPSEEK_*）仅作迁移期回退：必须显式标注
  ``source=legacy_env`` 且写审计告警，可观测、可逐步停用。
- 所有真实调用落模型账本（principal/agent/connection/binding 归属）。
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from src.platform.models.providers.base import (
    ChatMessage,
    ChatRequest,
    ProviderError,
)

LEGACY_ENV_SOURCE = "legacy_env"
MANAGED_SOURCE = "managed"


class ModelInvocationService:
    def __init__(self, services) -> None:
        self.services = services

    # ------------------------------------------------------------ resolve

    def resolve_agent_target(self, agent_id: str, *,
                             published_definition: dict | None
                             ) -> dict:
        """解析 Agent 的模型目标：受管引用 → managed；否则 legacy_env。"""
        defn = published_definition or {}
        provider = str(defn.get("provider") or "")
        model = str(defn.get("model") or "")
        if provider.startswith("connection:"):
            ref = provider[len("connection:"):]
            conn_id, _, vtxt = ref.partition("@v")
            try:
                version = int(vtxt)
            except ValueError:
                raise ProviderError(
                    f"Agent Definition provider 引用非法: {provider!r}")
            conn = self.services.repo.get_connection(
                tenant_id="local", connection_id=conn_id, version=version)
            if conn is None or conn.status != "active":
                raise ProviderError(
                    "Agent 绑定的 connection 版本不存在或非 active"
                    "（fail-closed，不静默降级）")
            return {"source": MANAGED_SOURCE,
                    "connection_id": conn_id,
                    "connection_version": version,
                    "adapter_kind": conn.adapter_kind,
                    "model_id": model,
                    "agent_id": agent_id}
        return {"source": LEGACY_ENV_SOURCE,
                "model_id": model or os.environ.get(
                    "DEEPSEEK_MODEL", "deepseek-chat"),
                "agent_id": agent_id}

    # -------------------------------------------------------------- chat

    def chat_for_agent(self, agent_id: str, *,
                       published_definition: dict | None,
                       messages: list[dict[str, str]],
                       principal_id: str,
                       run_id: str = "", work_id: str = "",
                       customer_id: str = "", project_id: str = "",
                       max_tokens: int = 1024) -> dict:
        """统一聊天调用：受管路径走 Adapter+账本；legacy 路径显式标注。"""
        target = self.resolve_agent_target(
            agent_id, published_definition=published_definition)
        if target["source"] == MANAGED_SOURCE:
            return self._chat_managed(target, messages=messages,
                                      principal_id=principal_id,
                                      run_id=run_id, work_id=work_id,
                                      customer_id=customer_id,
                                      project_id=project_id,
                                      max_tokens=max_tokens)
        return self._chat_legacy_env(target, messages=messages,
                                     principal_id=principal_id,
                                     agent_id=agent_id)

    def _chat_managed(self, target: dict, *, messages, principal_id,
                      run_id, work_id, customer_id, project_id,
                      max_tokens) -> dict:
        conn = self.services.repo.get_connection(
            tenant_id="local", connection_id=target["connection_id"],
            version=target["connection_version"])
        adapter = self.services._build_adapter(conn)
        req = ChatRequest(
            model_id=target["model_id"],
            messages=tuple(ChatMessage(role=m["role"],
                                       content=m["content"])
                           for m in messages),
            max_tokens=max_tokens)
        metering = self.services.metering
        from src.platform.models.metering import CallContext, Settlement
        ctx = CallContext(
            tenant_id="local", principal_id=principal_id,
            principal_kind="user", customer_id=customer_id,
            project_id=project_id, run_id=run_id, work_id=work_id,
            agent_id=target["agent_id"], module="agent",
            capability="chat",
            connection_id=target["connection_id"],
            connection_version=target["connection_version"],
            model_id=target["model_id"])
        call_id = metering.begin_call(
            ctx, reserved_output_tokens=float(max_tokens),
            request_amounts={"request": 1, "input_token": 0,
                             "output_token": float(max_tokens)})
        try:
            result = adapter.chat(req)
        except Exception as e:
            metering.settle_call(call_id, Settlement(
                ok=False, error_code=getattr(e, "code", "MODEL_ERROR"),
                meter_source="platform_observed"))
            raise
        metering.settle_call(call_id, Settlement(
            ok=True,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cached_input_tokens=result.usage.cached_input_tokens,
            reasoning_tokens=result.usage.reasoning_tokens,
            compute_ms=result.latency_ms,
            provider_request_id=result.provider_request_id,
            meter_source=("provider_reported" if result.usage_complete
                          else "platform_observed")))
        return {"source": MANAGED_SOURCE, "text": result.text,
                "model_id": result.model_id,
                "finish_reason": result.finish_reason,
                "usage": result.usage,
                "usage_complete": result.usage_complete,
                "provider_request_id": result.provider_request_id,
                "model_call_id": call_id}

    def _chat_legacy_env(self, target: dict, *, messages, principal_id,
                         agent_id) -> dict:
        """迁移期回退：仅当 DEEPSEEK_API_KEY 存在；显式标注来源并审计。"""
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        self._warn_legacy_fallback(agent_id, configured=bool(key))
        if not key:
            raise ProviderError(
                "legacy_env 回退未配置凭据：拒绝调用"
                "（请通过统一模型管理配置连接）")
        body = {"model": target["model_id"], "messages": messages,
                "temperature": 0.3}
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload = json.loads(r.read())
        except Exception as e:
            raise ProviderError(f"legacy_env 调用失败: {type(e).__name__}"
                                ) from None
        text = payload["choices"][0]["message"]["content"]
        return {"source": LEGACY_ENV_SOURCE, "text": text,
                "model_id": target["model_id"], "finish_reason": "",
                "usage": None, "usage_complete": False,
                "provider_request_id": "", "model_call_id": ""}

    def _warn_legacy_fallback(self, agent_id: str, *,
                              configured: bool) -> None:
        iam = getattr(self.services, "iam", None)
        if iam is None:
            return
        iam.audit("model-invocation", "model.legacy_env_fallback",
                  f"agent:{agent_id}",
                  {"configured": configured,
                   "note": "旧环境变量回退（迁移期）；应改经统一模型管理"})
        alerts = getattr(self.services, "alerts", None)
        if alerts is not None:
            try:
                alerts.raise_alert(
                    actor="model-invocation", role="system",
                    severity="warning", rule_id="legacy_env_fallback",
                    content=f"Agent {agent_id} 使用旧环境变量回退"
                            "（source=legacy_env），请迁移到统一模型管理",
                    recommended_action="配置受管连接与绑定")
            except Exception:
                pass
