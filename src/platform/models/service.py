"""ModelManagementServices：生命周期、probe、审批、CAS、回滚（M4/G3）。

状态机（01 §3、03 §7）：
- Connection: draft→testing→ready→pending_approval→active；
  测试失败回 draft（不影响 active）；active→superseded|disabled。
- Binding: draft→validated→pending_approval→canary→active→superseded；
  回滚 → rolled_back。canary 必须带明确 customer/project scope。

纪律：
- 生产变更（激活/停用/切换/回滚）必须 maker≠checker 经既有
  governance_approval_v1 账本（PolicyService.verify_approved）。
- 所有写操作 expected_revision/etag CAS；冲突 409；单赢家由条件
  UPDATE + 部分唯一索引保证。
- 跨主体资源统一零泄漏：不存在与无权同义。
- Resolver/Adapter 绝不解密 secret；secret 仅在 adapter 工厂的
  短租约闭包内出现。
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable, Mapping

from src.platform.governance.policy_service import PolicyService
from src.platform.models.contracts import (
    MODEL_CAPABILITY_MISMATCH,
    MODEL_IDENTITY_MISMATCH,
    MODEL_SECRET_UNAVAILABLE,
    MODEL_STATE_INVALID,
    BindingDraft,
    CasConflictError,
    CatalogManualEntry,
    ConnectionDraft,
    ContractError,
    IdentityMismatchError,
    ModelManagementError,
    StateMachineError,
)
from src.platform.models.endpoint_policy import (
    Endpoint,
    EndpointPolicy,
    EndpointPolicyError,
)
from src.platform.models.repository import (
    BindingVersionRow,
    CatalogEntryRow,
    ConnectionVersionRow,
    ModelRepository,
    compute_etag,
)
from src.platform.models.resolver import ModelResolver
from src.platform.models.secrets import (
    SecretNotFoundError,
    SecretScope,
    SecretStore,
    SecretStoreUnavailable,
)

CONN_APPROVAL_KIND = "model.connection.activate"
BINDING_APPROVAL_KIND = "model.binding.activate"
BINDING_ROLLBACK_KIND = "model.binding.rollback"
AGENT_REBIND_KIND = "model.agent.rebind"

AdapterFactory = Callable[
    [ConnectionVersionRow, Callable[[], bytes]], Any]


class ResourceNotFound(ModelManagementError):
    """资源不存在或跨主体不可见（统一零泄漏）。"""

    code = "MODEL_NOT_FOUND"
    http_status = 404


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9一-鿿]+", "-", name.strip()).strip("-")
    return slug.lower()[:64] or "connection"


def default_adapter_factory(row: ConnectionVersionRow,
                            get_secret: Callable[[], bytes]):
    """默认 Provider 工厂：EndpointPolicy 在调用侧第三次复用。"""
    endpoint = EndpointPolicy().validate(row.base_url,
                                         location=row.location)
    if row.adapter_kind == "anthropic":
        from src.platform.models.providers.anthropic import AnthropicAdapter
        return AnthropicAdapter(endpoint, get_secret=get_secret,
                                timeout_ms=row.timeout_ms,
                                max_retries=row.max_retries,
                                base_path=endpoint.path or None)
    from src.platform.models.providers.openai_compatible import (
        OpenAICompatibleAdapter)
    return OpenAICompatibleAdapter(
        endpoint, get_secret=get_secret, timeout_ms=row.timeout_ms,
        max_retries=row.max_retries, api_flavor=row.api_flavor or "auto")


class ModelManagementServices:
    """唯一模型管理组合（create_app 只装配一个实例）。"""

    def __init__(self, store, *,
                 secret_store: SecretStore | None = None,
                 iam=None,
                 adapter_factory: AdapterFactory | None = None,
                 policy: PolicyService | None = None,
                 endpoint_policy: EndpointPolicy | None = None) -> None:
        self.store = store
        self.repo = ModelRepository(store)
        self.resolver = ModelResolver(self.repo)
        self.secrets = secret_store
        self.iam = iam
        self.policy = policy or PolicyService(store)
        self._adapter_factory = adapter_factory or default_adapter_factory
        self._endpoint_policy = endpoint_policy or EndpointPolicy()
        # M6：账号级计量/预算/告警（复用既有 Governance Alert 账本）
        from src.platform.governance.alert_service import AlertService
        from src.platform.models.metering import (
            ModelBudgetService,
            ModelMeteringService,
        )
        self.alerts = AlertService(store)
        self.budgets = ModelBudgetService(store, alerts=self.alerts)
        self.metering = ModelMeteringService(
            store, budgets=self.budgets, alerts=self.alerts)

    # ------------------------------------------------------------- helpers

    def _audit(self, actor: str, action: str, resource: str,
               detail: dict | None = None) -> None:
        if self.iam is not None:
            self.iam.audit(actor, action, resource, detail or {})

    def _require_secrets(self) -> SecretStore:
        if self.secrets is None:
            raise SecretStoreUnavailable("SecretStore 未配置")
        return self.secrets

    def _get_connection(self, tenant_id: str, connection_id: str,
                        version: int) -> ConnectionVersionRow:
        row = self.repo.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version)
        if row is None:
            raise ResourceNotFound("connection 不存在或不可见")
        return row

    def _get_binding(self, tenant_id: str, binding_id: str,
                     version: int) -> BindingVersionRow:
        row = self.repo.get_binding(
            tenant_id=tenant_id, binding_id=binding_id, version=version)
        if row is None:
            raise ResourceNotFound("binding 不存在或不可见")
        return row

    def _secret_scope(self, row: ConnectionVersionRow) -> SecretScope:
        return SecretScope(tenant_id=row.tenant_id,
                           secret_ref=row.secret_ref,
                           adapter_kind=row.adapter_kind)

    def _build_adapter(self, row: ConnectionVersionRow):
        if row.location == "api" and not row.secret_ref:
            raise SecretStoreUnavailable(
                "connection 未配置凭据：拒绝调用")

        def get_secret() -> bytes:
            store = self._require_secrets()
            lease = store.lease(row.secret_ref, self._secret_scope(row))
            store.validate_lease(lease)
            return lease.value

        return self._adapter_factory(row, get_secret)

    # ---------------------------------------------------------- connection

    def create_connection_draft(self, *, tenant_id: str,
                                draft: ConnectionDraft, actor: str,
                                connection_id: str | None = None
                                ) -> ConnectionVersionRow:
        # EndpointPolicy 第一次复用：保存时
        self._endpoint_policy.validate(draft.base_url,
                                       location=draft.location.value)
        cid = connection_id or _slug(draft.name)
        version = self.repo.latest_connection_version(
            tenant_id=tenant_id, connection_id=cid) + 1
        # 新 draft 继承 connection 级 secret_ref（secret 属于连接而非版本）
        secret_ref = ""
        if version > 1:
            prev = self.repo.get_connection(
                tenant_id=tenant_id, connection_id=cid, version=version - 1)
            secret_ref = prev.secret_ref if prev else ""
        now = _utcnow_iso()
        row = ConnectionVersionRow(
            connection_id=cid, version=version, tenant_id=tenant_id,
            name=draft.name, location=draft.location.value,
            adapter_kind=draft.adapter_kind.value,
            api_flavor=draft.api_flavor, base_url=draft.base_url,
            secret_ref=secret_ref or f"model-secret/{cid}",
            timeout_ms=draft.timeout_ms, max_retries=draft.max_retries,
            config_json=draft.config.model_dump_json(), status="draft",
            etag=compute_etag("conn", cid, version, actor, now),
            approval_id=None, created_by=actor, created_at=now,
            activated_at=None)
        self.repo.insert_connection(row)
        self._audit(actor, "model.connection.draft",
                    f"{cid}@v{version}")
        return row

    def set_secret(self, *, tenant_id: str, connection_id: str,
                   version: int, value: bytes, actor: str) -> dict:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status not in ("draft", "testing", "ready"):
            raise StateMachineError(
                f"状态 {row.status} 不允许配置凭据")
        store = self._require_secrets()
        scope = self._secret_scope(row)
        try:
            meta = store.put(scope, value, actor)
        except SecretStoreUnavailable:
            raise
        except Exception:
            meta = store.rotate(scope, value, actor)
        new_etag = self.repo.set_connection_secret_ref(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version, secret_ref=scope.secret_ref,
            expected_etag=row.etag)
        self._audit(actor, "model.connection.secret_written",
                    f"{connection_id}@v{version}",
                    {"secret_version": meta.version})
        # write-only：响应只含元数据，绝不回显
        return {"secret_configured": True, "secret_version": meta.version,
                "etag": new_etag}

    def test_connection(self, *, tenant_id: str, connection_id: str,
                        version: int, actor: str) -> dict:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status not in ("draft", "failed"):
            raise StateMachineError(
                f"状态 {row.status} 不允许测试（测试失败回 draft，"
                "不影响 active）")
        self.repo.cas_connection_status(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version, from_status=("draft", "failed"),
            to_status="testing", expected_etag=row.etag)
        detail = {"probe": "auth_models"}
        try:
            # EndpointPolicy 第二次复用：连接测试前
            self._endpoint_policy.validate(row.base_url,
                                           location=row.location)
            adapter = self._build_adapter(row)
            models = adapter.list_models()
            detail["models_seen"] = len(models)
        except ModelManagementError as e:
            self._test_result(tenant_id, connection_id, version,
                              ok=False, detail=e.code)
            self._audit(actor, "model.connection.test_failed",
                        f"{connection_id}@v{version}", {"code": e.code})
            return {"status": "draft", "ok": False, "detail": e.code}
        self._test_result(tenant_id, connection_id, version, ok=True,
                          detail=json.dumps(detail, ensure_ascii=False))
        self._audit(actor, "model.connection.test_ok",
                    f"{connection_id}@v{version}")
        return {"status": "ready", "ok": True,
                "detail": detail}

    def _test_result(self, tenant_id: str, connection_id: str,
                     version: int, *, ok: bool, detail: str) -> None:
        row = self.repo.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version)
        if row is None:
            return
        self.repo.cas_connection_status(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version, from_status="testing",
            to_status="ready" if ok else "draft",
            expected_etag=row.etag)

    def submit_connection(self, *, tenant_id: str, connection_id: str,
                          version: int, actor: str,
                          expected_etag: str | None = None) -> dict:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status != "ready":
            raise StateMachineError("只有 ready 可申请启用")
        if row.location == "api" and not row.secret_ref:
            raise StateMachineError("api 连接必须先配置凭据")
        if expected_etag is not None and expected_etag != row.etag:
            raise CasConflictError("expected_revision 不匹配")
        approval = self.policy.request_generic_approval(
            kind=CONN_APPROVAL_KIND,
            subject_ref=f"{connection_id}@v{version}",
            requested_by=actor)
        self.repo.cas_connection_status(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version, from_status="ready",
            to_status="pending_approval", expected_etag=row.etag,
            approval_id=approval["approval_id"])
        self._audit(actor, "model.connection.submit",
                    f"{connection_id}@v{version}")
        return {"approval_id": approval["approval_id"],
                "status": "pending_approval"}

    def approve_connection(self, *, tenant_id: str, connection_id: str,
                           version: int, approver: str,
                           approval_id: str) -> dict:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status != "pending_approval":
            raise StateMachineError("只有 pending_approval 可批准")
        # maker≠checker 由账本强制（requested_by != approver）
        self.policy.verify_approved(
            approval_id, kind=CONN_APPROVAL_KIND,
            subject_ref=f"{connection_id}@v{version}", approver=approver,
            created_by=row.created_by)
        conn = self.store._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            new_etag = self.repo.cas_connection_status(
                tenant_id=tenant_id, connection_id=connection_id,
                version=version, from_status="pending_approval",
                to_status="active", expected_etag=row.etag,
                activated_at=_utcnow_iso())
            self.repo.supersede_other_active_connections(
                tenant_id=tenant_id, connection_id=connection_id,
                keep_version=version)
            conn.execute("COMMIT")
        except LookupError as e:
            conn.execute("ROLLBACK")
            raise CasConflictError(str(e)) from e
        except Exception:
            conn.execute("ROLLBACK")
            raise
        self._audit(approver, "model.connection.activate",
                    f"{connection_id}@v{version}")
        return {"status": "active", "etag": new_etag}

    def reject_connection(self, *, tenant_id: str, connection_id: str,
                          version: int, approver: str,
                          approval_id: str) -> dict:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status != "pending_approval":
            raise StateMachineError("只有 pending_approval 可拒绝")
        ap = self.policy.get_approval(approval_id)
        if ap["kind"] != CONN_APPROVAL_KIND or \
                ap["subject_ref"] != f"{connection_id}@v{version}":
            raise ContractError("approval 与目标不匹配")
        if ap["decision"] != "rejected" or ap["decided_by"] != approver:
            raise StateMachineError("approval 未被该审批人拒绝")
        new_etag = self._cas_or_conflict(lambda: self.repo
                                         .cas_connection_status(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version, from_status="pending_approval",
            to_status="rejected", expected_etag=row.etag))
        return {"status": "rejected", "etag": new_etag}

    def disable_connection(self, *, tenant_id: str, connection_id: str,
                           version: int, actor: str,
                           expected_etag: str | None = None) -> dict:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status != "active":
            raise StateMachineError("只有 active 可停用")
        if expected_etag is not None and expected_etag != row.etag:
            raise CasConflictError("expected_revision 不匹配")
        new_etag = self._cas_or_conflict(lambda: self.repo
                                         .cas_connection_status(
            tenant_id=tenant_id, connection_id=connection_id,
            version=version, from_status="active", to_status="disabled",
            expected_etag=row.etag))
        self._audit(actor, "model.connection.disable",
                    f"{connection_id}@v{version}")
        return {"status": "disabled", "etag": new_etag}

    def _cas_or_conflict(self, fn: Callable[[], str]) -> str:
        try:
            return fn()
        except LookupError as e:
            raise CasConflictError(str(e)) from e

    # ------------------------------------------------------------- catalog

    def discover_models(self, *, tenant_id: str, connection_id: str,
                        version: int, actor: str) -> list[dict]:
        row = self._get_connection(tenant_id, connection_id, version)
        if row.status not in ("ready", "active", "testing"):
            raise StateMachineError(
                f"状态 {row.status} 不允许发现模型")
        adapter = self._build_adapter(row)
        try:
            models = adapter.list_models()
        except ModelManagementError as e:
            raise _discovery_error(e) from e
        out = []
        for m in models:
            entry = CatalogEntryRow(
                catalog_id=f"cat-{connection_id}-v{version}-{m.model_id}",
                tenant_id=tenant_id, connection_id=connection_id,
                connection_version=version, model_id=m.model_id,
                model_revision=m.revision, capabilities_json="[]",
                embedding_dimension=None, normalization_version=None,
                source="discovered", probe_status="unprobed",
                probe_json="{}", last_verified_at=None)
            self.repo.upsert_catalog(entry)
            out.append({"catalog_id": entry.catalog_id,
                        "model_id": m.model_id})
        self._audit(actor, "model.catalog.discover",
                    f"{connection_id}@v{version}",
                    {"count": len(out)})
        return out

    def register_manual(self, *, tenant_id: str, connection_id: str,
                        version: int, entry: CatalogManualEntry,
                        actor: str) -> CatalogEntryRow:
        self._get_connection(tenant_id, connection_id, version)
        row = CatalogEntryRow(
            catalog_id=f"cat-{connection_id}-v{version}-{entry.model_id}",
            tenant_id=tenant_id, connection_id=connection_id,
            connection_version=version, model_id=entry.model_id,
            model_revision=entry.model_revision,
            capabilities_json=json.dumps(
                [c.value for c in entry.capabilities]),
            embedding_dimension=entry.embedding_dimension,
            normalization_version=entry.normalization_version,
            source="manual", probe_status="unprobed", probe_json="{}",
            last_verified_at=None)
        self.repo.upsert_catalog(row)
        self._audit(actor, "model.catalog.manual", row.catalog_id)
        return row

    def probe_model(self, *, tenant_id: str, catalog_id: str,
                    actor: str) -> dict:
        cat = self.repo.get_catalog(tenant_id=tenant_id,
                                    catalog_id=catalog_id)
        if cat is None:
            raise ResourceNotFound("catalog 不存在或不可见")
        conn = self.repo.get_connection(
            tenant_id=tenant_id, connection_id=cat.connection_id,
            version=cat.connection_version)
        if conn is None or conn.status not in ("ready", "active"):
            raise StateMachineError("connection 未就绪，无法 probe")
        capabilities = _load_list(cat.capabilities_json)
        if not capabilities:
            raise StateMachineError(
                "目录未声明能力：不得根据模型名猜测，先声明再 probe")
        adapter = self._build_adapter(conn)
        results: dict[str, Any] = {}
        all_ok = True
        dimension: int | None = None
        for cap in capabilities:
            try:
                probe = adapter.probe(cat.model_id, cap)
            except ModelManagementError as e:
                probe = None
                results[cap] = {"ok": False, "detail": e.code}
                all_ok = False
            if probe is not None:
                results[cap] = {"ok": probe.ok, "detail": probe.detail}
                if probe.ok and probe.dimension:
                    dimension = probe.dimension
                all_ok = all_ok and probe.ok
        self.repo.update_catalog_probe(
            tenant_id=tenant_id, catalog_id=catalog_id,
            probe_status="ready" if all_ok else "failed",
            probe_json=json.dumps(results, ensure_ascii=False),
            embedding_dimension=dimension)
        self._audit(actor, "model.catalog.probe", catalog_id,
                    {"ok": all_ok})
        return {"catalog_id": catalog_id,
                "probe_status": "ready" if all_ok else "failed",
                "results": results, "embedding_dimension": dimension}

    # ------------------------------------------------------------- binding

    def create_binding_draft(self, *, tenant_id: str, draft: BindingDraft,
                             actor: str, binding_id: str | None = None
                             ) -> BindingVersionRow:
        bid = binding_id or _slug(
            f"{draft.subject_kind.value}-{draft.subject_id}-"
            f"{draft.capability.value}")
        version = self.repo.latest_binding_version(
            tenant_id=tenant_id, binding_id=bid) + 1
        now = _utcnow_iso()
        row = BindingVersionRow(
            binding_id=bid, version=version, tenant_id=tenant_id,
            customer_id=draft.customer_id, project_id=draft.project_id,
            subject_kind=draft.subject_kind.value,
            subject_id=draft.subject_id,
            capability=draft.capability.value,
            connection_id=draft.connection_id,
            connection_version=draft.connection_version,
            model_id=draft.model_id,
            fallback_json=json.dumps(
                [f.model_dump() for f in draft.fallback]),
            status="draft",
            etag=compute_etag("binding", bid, version, actor, now),
            approval_id=None, created_by=actor, created_at=now,
            activated_at=None)
        self.repo.insert_binding(row)
        self._audit(actor, "model.binding.draft", f"{bid}@v{version}")
        return row

    def validate_binding(self, *, tenant_id: str, binding_id: str,
                         version: int, actor: str,
                         expected_etag: str | None = None) -> dict:
        row = self._get_binding(tenant_id, binding_id, version)
        if row.status != "draft":
            raise StateMachineError("只有 draft 可校验")
        if expected_etag is not None and expected_etag != row.etag:
            raise CasConflictError("expected_revision 不匹配")
        impact = self._binding_impact(row)
        new_etag = self._cas_or_conflict(lambda: self.repo
                                         .cas_binding_status(
            tenant_id=tenant_id, binding_id=binding_id, version=version,
            from_status="draft", to_status="validated",
            expected_etag=row.etag))
        self._audit(actor, "model.binding.validate",
                    f"{binding_id}@v{version}")
        return {"status": "validated", "etag": new_etag,
                "impact": impact}

    def _binding_impact(self, row: BindingVersionRow) -> dict:
        conn = self.repo.get_connection(
            tenant_id=row.tenant_id, connection_id=row.connection_id,
            version=row.connection_version)
        if conn is None:
            raise ResourceNotFound("binding 指向的 connection 不存在")
        if conn.status not in ("ready", "pending_approval", "active"):
            raise StateMachineError(
                f"connection 状态 {conn.status} 不可绑定")
        cat = self.repo.find_catalog_model(
            tenant_id=row.tenant_id, connection_id=row.connection_id,
            connection_version=row.connection_version,
            model_id=row.model_id)
        if cat is None:
            raise ResourceNotFound("binding 指向的模型不在目录")
        if cat.probe_status != "ready":
            raise StateMachineError(
                "未通过 probe 的模型不能绑定为 candidate")
        caps = _load_list(cat.capabilities_json)
        if row.capability not in caps:
            raise ModelManagementError(
                f"能力不匹配：{row.capability} 不在目录能力中")
        # 影响分析：当前同 scope key 的 active 绑定与索引重建需求
        current = None
        for b in self.repo.candidate_bindings(tenant_id=row.tenant_id):
            if (b.status == "active" and b.customer_id == row.customer_id
                    and b.project_id == row.project_id
                    and b.subject_kind == row.subject_kind
                    and b.subject_id == row.subject_id
                    and b.capability == row.capability):
                current = b
                break
        rebuild_required = False
        if row.capability == "embedding":
            if current is not None and (
                    current.connection_id != row.connection_id
                    or current.connection_version != row.connection_version
                    or current.model_id != row.model_id):
                rebuild_required = True
            elif current is None:
                rebuild_required = True
        rollback_target = None
        if current is not None:
            rollback_target = (f"{current.binding_id}@"
                               f"v{current.version}")
        return {
            "connection_status": conn.status,
            "replaces": (f"{current.binding_id}@v{current.version}"
                         if current else None),
            "index_rebuild_required": rebuild_required,
            "rollback_target": rollback_target,
            "affected_subject": f"{row.subject_kind}:{row.subject_id}",
        }

    def submit_binding(self, *, tenant_id: str, binding_id: str,
                       version: int, actor: str,
                       expected_etag: str | None = None) -> dict:
        row = self._get_binding(tenant_id, binding_id, version)
        if row.status != "validated":
            raise StateMachineError("只有 validated 可提交")
        if expected_etag is not None and expected_etag != row.etag:
            raise CasConflictError("expected_revision 不匹配")
        approval = self.policy.request_generic_approval(
            kind=BINDING_APPROVAL_KIND,
            subject_ref=f"{binding_id}@v{version}", requested_by=actor)
        self._cas_or_conflict(lambda: self.repo.cas_binding_status(
            tenant_id=tenant_id, binding_id=binding_id, version=version,
            from_status="validated", to_status="pending_approval",
            expected_etag=row.etag,
            approval_id=approval["approval_id"]))
        self._audit(actor, "model.binding.submit",
                    f"{binding_id}@v{version}")
        return {"approval_id": approval["approval_id"],
                "status": "pending_approval"}

    def _verify_binding_approval(self, row: BindingVersionRow, *,
                                 approval_id: str, approver: str,
                                 kind: str = BINDING_APPROVAL_KIND
                                 ) -> None:
        self.policy.verify_approved(
            approval_id, kind=kind,
            subject_ref=f"{row.binding_id}@v{row.version}",
            approver=approver, created_by=row.created_by)

    def activate_canary(self, *, tenant_id: str, binding_id: str,
                        version: int, approver: str, approval_id: str,
                        expected_etag: str | None = None) -> dict:
        row = self._get_binding(tenant_id, binding_id, version)
        if row.status != "pending_approval":
            raise StateMachineError("只有 pending_approval 可进入 canary")
        if not row.customer_id and not row.project_id:
            raise StateMachineError(
                "canary 必须带明确 customer/project scope；"
                "空范围不得解释为全量")
        if expected_etag is not None and expected_etag != row.etag:
            raise CasConflictError("expected_revision 不匹配")
        self._verify_binding_approval(row, approval_id=approval_id,
                                      approver=approver)
        self._binding_impact(row)  # 激活前复核连接/模型仍然有效
        new_etag = self._activate_binding_cas(
            row, to_status="canary", expected_etag=row.etag,
            approval_id=approval_id)
        self._audit(approver, "model.binding.canary",
                    f"{binding_id}@v{version}")
        return {"status": "canary", "etag": new_etag}

    def activate_binding(self, *, tenant_id: str, binding_id: str,
                         version: int, approver: str, approval_id: str,
                         expected_etag: str | None = None) -> dict:
        row = self._get_binding(tenant_id, binding_id, version)
        if row.status not in ("pending_approval", "canary"):
            raise StateMachineError(
                "只有 pending_approval/canary 可激活")
        if expected_etag is not None and expected_etag != row.etag:
            raise CasConflictError("expected_revision 不匹配")
        self._verify_binding_approval(row, approval_id=approval_id,
                                      approver=approver)
        self._binding_impact(row)
        new_etag = self._activate_binding_cas(
            row, to_status="active", expected_etag=row.etag,
            approval_id=approval_id)
        self._audit(approver, "model.binding.activate",
                    f"{binding_id}@v{version}")
        return {"status": "active", "etag": new_etag}

    def _activate_binding_cas(self, row: BindingVersionRow, *,
                              to_status: str, expected_etag: str,
                              approval_id: str) -> str:
        conn = self.store._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            new_etag = self.repo.cas_binding_status(
                tenant_id=row.tenant_id, binding_id=row.binding_id,
                version=row.version, from_status=(
                    "pending_approval", "canary"),
                to_status=to_status, expected_etag=expected_etag,
                approval_id=approval_id, activated_at=_utcnow_iso())
            scope_key = {
                "customer_id": row.customer_id,
                "project_id": row.project_id,
                "subject_kind": row.subject_kind,
                "subject_id": row.subject_id,
                "capability": row.capability,
            }
            self.repo.supersede_other_active_bindings(
                tenant_id=row.tenant_id, scope_key=scope_key,
                keep_binding_id=row.binding_id, keep_version=row.version)
            if to_status == "active":
                # 同 scope 的 canary 一并 superseded（已被全量激活取代）
                conn.execute(
                    "UPDATE model_binding_version_v1 SET"
                    " status='superseded' WHERE tenant_id=? AND"
                    " customer_id=? AND project_id=? AND subject_kind=?"
                    " AND subject_id=? AND capability=? AND"
                    " status='canary' AND NOT (binding_id=? AND"
                    " version=?)",
                    (row.tenant_id, row.customer_id, row.project_id,
                     row.subject_kind, row.subject_id, row.capability,
                     row.binding_id, row.version))
            conn.execute("COMMIT")
            return new_etag
        except LookupError as e:
            conn.execute("ROLLBACK")
            raise CasConflictError(str(e)) from e
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def rollback_binding(self, *, tenant_id: str, binding_id: str,
                         to_version: int, approver: str, approval_id: str,
                         index_snapshot_id: str | None = None) -> dict:
        target = self._get_binding(tenant_id, binding_id, to_version)
        if target.status not in ("superseded",):
            raise StateMachineError(
                "回滚目标必须是已批准且被取代的历史版本")
        # 回滚也要 maker≠checker 审批
        self.policy.verify_approved(
            approval_id, kind=BINDING_ROLLBACK_KIND,
            subject_ref=f"{binding_id}@v{to_version}",
            approver=approver, created_by=target.created_by)
        conn_row = self.repo.get_connection(
            tenant_id=tenant_id, connection_id=target.connection_id,
            version=target.connection_version)
        if conn_row is None or conn_row.status != "active":
            raise StateMachineError(
                "回滚目标的 connection 版本必须仍然 active")
        cat = self.repo.find_catalog_model(
            tenant_id=tenant_id, connection_id=target.connection_id,
            connection_version=target.connection_version,
            model_id=target.model_id)
        if cat is None or cat.probe_status != "ready":
            raise StateMachineError("回滚目标的模型必须仍通过 probe")
        # 当前 active/canary 版本
        current = None
        for b in self.repo.candidate_bindings(tenant_id=tenant_id):
            if (b.binding_id == binding_id
                    and b.customer_id == target.customer_id
                    and b.project_id == target.project_id
                    and b.subject_kind == target.subject_kind
                    and b.subject_id == target.subject_id
                    and b.capability == target.capability):
                current = b
                break
        if current is None:
            raise StateMachineError("没有可回滚的 active/canary 版本")
        if target.capability == "embedding":
            self._check_embedding_rollback_identity(
                target, cat, index_snapshot_id)
        conn = self.store._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            self._cas_or_conflict(lambda: self.repo.cas_binding_status(
                tenant_id=tenant_id, binding_id=current.binding_id,
                version=current.version,
                from_status=("active", "canary"),
                to_status="rolled_back", expected_etag=current.etag))
            new_etag = self._cas_or_conflict(
                lambda: self.repo.cas_binding_status(
                    tenant_id=tenant_id, binding_id=binding_id,
                    version=to_version, from_status="superseded",
                    to_status="active", expected_etag=target.etag,
                    approval_id=approval_id,
                    activated_at=_utcnow_iso()))
            conn.execute("COMMIT")
        except CasConflictError:
            conn.execute("ROLLBACK")
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise
        self._audit(approver, "model.binding.rollback",
                    f"{binding_id}@v{to_version}")
        return {"status": "active", "etag": new_etag,
                "rolled_back": f"{current.binding_id}@"
                               f"v{current.version}"}

    # ------------------------------------------------ agent model changes

    def propose_agent_model_change(self, *, agent_runtime, agent_id: str,
                                   connection_id: str,
                                   connection_version: int, model_id: str,
                                   actor: str) -> dict:
        """UI/API 修改 Agent 模型：只在 Agent Definition 上创建新 draft。

        DEC-M004：Agent Definition 是唯一事实源；本方法只替换
        provider/model，其余字段（Soul/Prompt/Tools/Budget/Memory ACL）
        由 save_draft 从现行定义原样继承，不产生第二份配置。
        """
        conn = self.repo.get_connection(
            tenant_id="local", connection_id=connection_id,
            version=connection_version)
        if conn is None or conn.status != "active":
            raise StateMachineError(
                "Agent 只能绑定 active connection 版本")
        cat = self.repo.find_catalog_model(
            tenant_id="local", connection_id=connection_id,
            connection_version=connection_version, model_id=model_id)
        if cat is None or cat.probe_status != "ready":
            raise StateMachineError("目标模型未通过 probe，不能绑定")
        caps = _load_list(cat.capabilities_json)
        if not ({"chat", "reasoning"} & set(caps)):
            raise StateMachineError(
                "目标模型不具备 chat/reasoning 能力")
        draft = agent_runtime.save_draft(
            agent_id, actor=actor,
            provider=f"connection:{connection_id}@v{connection_version}",
            model=model_id)
        self._audit(actor, "model.agent.draft",
                    f"agent:{agent_id}@v{draft['version']}",
                    {"connection_id": connection_id, "model_id": model_id})
        return {"agent_id": agent_id, "version": draft["version"],
                "status": "draft"}

    def submit_agent_model_change(self, *, agent_id: str, version: int,
                                  actor: str) -> dict:
        approval = self.policy.request_generic_approval(
            kind=AGENT_REBIND_KIND,
            subject_ref=f"agent:{agent_id}@v{version}",
            requested_by=actor)
        self._audit(actor, "model.agent.submit",
                    f"agent:{agent_id}@v{version}")
        return {"approval_id": approval["approval_id"],
                "status": "pending_approval"}

    def approve_agent_model_change(self, *, agent_runtime, agent_id: str,
                                   version: int, approver: str,
                                   approval_id: str) -> dict:
        """checker 批准 → 发布 draft 并重建 Manifest 投影。"""
        self.policy.verify_approved(
            approval_id, kind=AGENT_REBIND_KIND,
            subject_ref=f"agent:{agent_id}@v{version}",
            approver=approver)
        published = agent_runtime.publish(agent_id, version,
                                          actor=approver)
        from src.platform.agents.manifest_projection import (
            rebuild_manifest_projection)
        rebuild_manifest_projection(self.store)
        self._audit(approver, "model.agent.activate",
                    f"agent:{agent_id}@v{version}")
        return {"agent_id": agent_id, "version": published["version"],
                "status": "published",
                "provider": published["provider"],
                "model": published["model"]}

    def rollback_agent_model(self, *, agent_runtime, agent_id: str,
                             actor: str) -> dict:
        out = agent_runtime.rollback(agent_id, actor=actor)
        from src.platform.agents.manifest_projection import (
            rebuild_manifest_projection)
        rebuild_manifest_projection(self.store)
        self._audit(actor, "model.agent.rollback", f"agent:{agent_id}")
        return out

    def _check_embedding_rollback_identity(self, target: BindingVersionRow,
                                           cat: CatalogEntryRow,
                                           index_snapshot_id: str | None
                                           ) -> None:
        """Embedding 回滚必须恢复匹配的 active index snapshot；
        没有匹配索引则拒绝（03 §8）。"""
        conn = self.store._conn
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "cognition_index_activation_v1" not in tables:
            raise IdentityMismatchError(
                "embedding 回滚需要索引账本，当前不可用")
        if not index_snapshot_id:
            raise IdentityMismatchError(
                "embedding 回滚必须提供匹配的 index_snapshot_id")
        row = conn.execute(
            "SELECT b.build_status, b.embedding_model FROM"
            " cognition_index_activation_v1 a JOIN"
            " cognition_index_build_v1 b ON"
            " b.index_snapshot_id = a.index_snapshot_id WHERE"
            " a.index_snapshot_id=? AND a.status='active'",
            (index_snapshot_id,)).fetchone()
        if row is None:
            raise IdentityMismatchError(
                "index snapshot 不存在或非 active")
        identity = row["embedding_model"] or ""
        if cat.model_id not in identity:
            raise IdentityMismatchError(
                "index snapshot 与回滚目标模型身份不匹配")

    # ------------------------------------------------------------- queries

    def public_connection_view(self, row: ConnectionVersionRow) -> dict:
        view = {
            "connection_id": row.connection_id,
            "version": row.version,
            "tenant_id": row.tenant_id,
            "name": row.name,
            "location": row.location,
            "adapter_kind": row.adapter_kind,
            "api_flavor": row.api_flavor,
            "base_url": row.base_url,
            "timeout_ms": row.timeout_ms,
            "max_retries": row.max_retries,
            "status": row.status,
            "etag": row.etag,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "activated_at": row.activated_at,
            "secret_configured": False,
            "secret_version": None,
            "last_rotated_at": None,
        }
        if row.secret_ref and self.secrets is not None:
            try:
                meta = self.secrets.metadata(row.secret_ref)
                view["secret_configured"] = meta["status"] != "revoked"
                view["secret_version"] = meta["version"]
                view["last_rotated_at"] = meta["rotated_at"]
            except SecretNotFoundError:
                pass
        return view


def _discovery_error(e: ModelManagementError) -> ModelManagementError:
    if e.code == MODEL_SECRET_UNAVAILABLE:
        return SecretStoreUnavailable("模型发现失败：凭据不可用")
    return e


def _load_list(raw: str) -> list:
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []
