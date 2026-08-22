"""ModelResolver：scope-first 绑定解析（M4/G3，01 §5）。

纪律：
- 候选必须先按 tenant（repository SQL）再按 customer/project/状态/
  生效时间过滤，之后才排序；跨租户不可见是查询结构保证，不是排序技巧。
- disabled/failed/rejected/draft/pending_approval 的连接与绑定绝不返回。
- canary 只在请求 scope 与其明确 customer/project 完全匹配时命中；
  空 scope canary 视为无效（不得解释为全量）。
- Resolver 只读，绝不解密 secret；凭据由 Adapter 经 SecretStore 换取。
- Agent 模型事实源仍是 Agent Definition：通过注入的
  ``agent_definition_lookup`` 返回 source="agent_definition"。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from src.platform.models.contracts import ResolveRequest
from src.platform.models.repository import (
    BindingVersionRow,
    CatalogEntryRow,
    ModelRepository,
)

# 解析优先级（01 §5）：
#   agent_definition → project 模块绑定 → customer 模块绑定 →
#   tenant 模块绑定 → project capability default → customer →
#   tenant → deployment default（tenant 级 system_capability 默认）。
_SUBJECT_RANK = {"module": 2, "system_capability": 1}


@dataclass(frozen=True)
class ResolvedModel:
    connection_id: str
    connection_version: int
    adapter_kind: str
    location: str
    model_id: str
    model_revision: str
    capability: str
    embedding_dimension: int | None
    normalization_version: str | None
    binding_id: str
    binding_version: int
    source: str  # managed | agent_definition | legacy_env


AgentLookup = Callable[[ResolveRequest], Mapping[str, str] | None]


class ModelResolver:
    def __init__(self, repo: ModelRepository, *,
                 agent_definition_lookup: AgentLookup | None = None) -> None:
        self._repo = repo
        self._agent_lookup = agent_definition_lookup

    def resolve(self, req: ResolveRequest) -> ResolvedModel | None:
        # 1) Agent published Definition 是唯一 Agent 模型事实源
        if self._agent_lookup is not None:
            agent = self._agent_lookup(req)
            if agent:
                return ResolvedModel(
                    connection_id=str(agent.get("connection_id", "")),
                    connection_version=int(
                        agent.get("connection_version", 0) or 0),
                    adapter_kind=str(agent.get("adapter_kind", "")),
                    location=str(agent.get("location", "")),
                    model_id=str(agent.get("model_id", "")),
                    model_revision=str(agent.get("model_revision", "")),
                    capability=req.capability.value,
                    embedding_dimension=_opt_int(
                        agent.get("embedding_dimension")),
                    normalization_version=_opt_str(
                        agent.get("normalization_version")),
                    binding_id=str(agent.get("binding_id", "")),
                    binding_version=int(agent.get("binding_version", 0) or 0),
                    source="agent_definition")

        # 2) 受管绑定：候选（仅 active/canary）→ scope-first 过滤 → 排序
        candidates = self._repo.candidate_bindings(
            tenant_id=req.tenant_id)
        visible = [b for b in candidates
                   if self._visible(b, req) and self._effective(b, req)]
        ranked = sorted(visible, key=lambda b: self._rank(b, req),
                        reverse=True)
        for binding in ranked:
            conn = self._repo.get_connection(
                tenant_id=req.tenant_id,
                connection_id=binding.connection_id,
                version=binding.connection_version)
            if conn is None or conn.status != "active":
                # fail-closed：绑定指向的连接版本必须 active
                continue
            catalog = self._repo.find_catalog_model(
                tenant_id=req.tenant_id,
                connection_id=binding.connection_id,
                connection_version=binding.connection_version,
                model_id=binding.model_id)
            if catalog is None or catalog.probe_status != "ready":
                # fail-closed：未通过 probe 的模型不得被解析
                continue
            caps = _load_list(catalog.capabilities_json)
            if req.capability.value not in caps:
                continue
            return ResolvedModel(
                connection_id=conn.connection_id,
                connection_version=conn.version,
                adapter_kind=conn.adapter_kind,
                location=conn.location,
                model_id=binding.model_id,
                model_revision=catalog.model_revision,
                capability=req.capability.value,
                embedding_dimension=catalog.embedding_dimension,
                normalization_version=catalog.normalization_version,
                binding_id=binding.binding_id,
                binding_version=binding.version,
                source="managed")
        return None

    # ------------------------------------------------------------ filters

    def _visible(self, b: BindingVersionRow, req: ResolveRequest) -> bool:
        """scope-first 过滤：customer/project 维度。

        - canary 必须带明确 scope（空 scope canary 无效，01 §3）；
        - 绑定声明的 customer/project 非空时必须与请求完全一致。"""
        if b.status == "canary":
            if not b.customer_id and not b.project_id:
                return False
            if b.customer_id and b.customer_id != req.customer_id:
                return False
            if b.project_id and b.project_id != req.project_id:
                return False
            return True
        if b.customer_id and b.customer_id != req.customer_id:
            return False
        if b.project_id and b.project_id != req.project_id:
            return False
        return True

    def _effective(self, b: BindingVersionRow, req: ResolveRequest) -> bool:
        if not b.activated_at:
            return False
        try:
            activated = datetime.fromisoformat(b.activated_at)
            as_of = datetime.fromisoformat(req.as_of)
        except ValueError:
            return False
        if activated.tzinfo is None or as_of.tzinfo is None:
            return False
        return activated <= as_of

    def _rank(self, b: BindingVersionRow,
              req: ResolveRequest) -> tuple[int, int, int]:
        subject_rank = _SUBJECT_RANK.get(b.subject_kind, 0)
        if b.subject_kind == "module":
            subject_rank = 2 if b.subject_id == req.subject_id else -1
        elif b.subject_kind == "system_capability":
            # capability default：subject_id == capability 名
            subject_rank = 1 if b.subject_id == req.capability.value else -1
        if b.project_id and b.project_id == req.project_id:
            scope_rank = 3
        elif b.customer_id and b.customer_id == req.customer_id:
            scope_rank = 2
        elif not b.customer_id and not b.project_id:
            scope_rank = 1  # tenant/deployment default
        else:
            scope_rank = 0
        # canary 在其明确 scope 内服务新流量，优先于旧 active 版本
        status_rank = 2 if b.status == "canary" else 1
        return (subject_rank, scope_rank, status_rank)


def _load_list(raw: str) -> list:
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _opt_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _opt_str(value) -> str | None:
    return value if isinstance(value, str) and value else None
