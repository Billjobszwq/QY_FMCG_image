"""ABOSV2 Phase B：Command Gateway（统一 Work/Event/Usage 控制平面）。

所有 Web/API/Agent 入口共用本 gateway：
  command → BusinessRun + WorkItemV2 → 领域节点执行 → Domain Record
  → EventEnvelope（Outbox 同事务）→ UsageEventV2 → EvidenceBundleV1
  → current projection（可从事件重建，hash/count 对账）。

失败不是终点：failed run 保留错误与事件，retry 以 run.retried 事件
推动恢复；failed 不得直接变 succeeded（store 状态机强制）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from typing import Any

from .api.recognition_tasks import run_recognition_batch
from .scope import ScopeResolver, ScopeViolation

RUN_FAILED = "failed"


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:16]


class CommandGatewayError(Exception):
    """gateway 层错误（命令不支持等）。"""


class CommandGateway:
    # 已注册领域命令（fail-closed）：Workflow 节点库与 lint 同源消费
    SUPPORTED_COMMANDS = ("vision.recognition.create",)

    def __init__(self, store: Any, profiles_service: Any | None,
                 recognition_adapter: Any | None) -> None:
        self.store = store
        self.profiles_service = profiles_service
        self.recognition_adapter = recognition_adapter
        # retry 重放：保存解码后的输入（bytes 不入 DB；进程重启后
        # 失败 run 需重新提交命令，属诚实降级）
        self._replay_images: dict[str, list[tuple[str, bytes]]] = {}

    # ---------- 对外入口 ----------

    def submit(self, *, command_kind: str, params: dict[str, Any],
               actor: str, source: str,
               idempotency_key: str | None = None,
               correlation_id: str | None = None,
               goal_id: str = "", tenant_id: str = "local",
               customer_id: str = "", project_id: str = "",
               parent_run_id: str | None = None,
               test_run_id: str = "",
               ) -> dict[str, Any]:
        # 幂等：同一键返回同一 run（不重复执行副作用）
        if idempotency_key:
            hit = self.store.find_business_run_by_idempotency_key(
                idempotency_key)
            if hit is not None:
                return {"run_id": hit["run_id"],
                        "work_id": hit["work_id"],
                        "status": hit["status"],
                        "idempotent_replay": True,
                        "result": self._result_from_run(hit)}
        if command_kind not in self.SUPPORTED_COMMANDS:
            raise CommandGatewayError(
                f"未注册的命令: {command_kind}（fail-closed）")
        corr = correlation_id or "corr-" + uuid.uuid4().hex[:12]
        run_id, work_id = _new_id("run"), _new_id("work")
        # SI2 T2：服务端解析执行作用域（fail-closed；客户端不得自证
        # operational）。父 fixture 产生 operational 子对象 → 拒绝。
        scope = ScopeResolver(self.store).resolve(
            parent_run_id=parent_run_id, test_run_id=test_run_id,
            customer_id=customer_id, project_id=project_id,
            actor_id=actor, source=source, correlation_id=corr,
            tenant_id=tenant_id)
        images = self._decode_images(params.get("images", []))
        self._replay_images[run_id] = images
        # 入库 params 脱敏：bytes 不落库（只记图片数），保证可序列化；
        # source/entry 随 params 保存，供 retry 重放同一入口语义
        stored_params = {k: v for k, v in params.items() if k != "images"}
        stored_params["image_count"] = len(images)
        stored_params.setdefault("source", source)
        # 同一事务：run + work + command.accepted 事件 + outbox
        self.store.insert_business_run({
            "run_id": run_id, "work_id": work_id, "tenant_id": tenant_id,
            "customer_id": scope.customer_id,
            "project_id": scope.project_id,
            "trigger_type": "command", "correlation_id": corr,
            "parent_run_id": parent_run_id,
            "initiator_type": "agent" if source == "agent" else "human",
            "initiator_id": actor, "status": "queued",
            "command_kind": command_kind, "params": stored_params,
            "idempotency_key": idempotency_key, "goal_id": goal_id,
            "workflow_definition_id": "recognition_inline_v1",
            "workflow_version": "1",
            "data_scope": scope.data_scope,
            "test_run_id": scope.test_run_id})
        self.store.insert_work_item_v2({
            "work_id": work_id, "tenant_id": tenant_id,
            "customer_id": scope.customer_id,
            "project_id": scope.project_id,
            "run_id": run_id, "status": "running",
            "owner_type": "system", "owner_id": "recognition_node",
            "title": "识别任务执行",
            "business_summary": f"{command_kind} · 来源 {source}",
            "idempotency_key": idempotency_key,
            "data_scope": scope.data_scope})
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="command.accepted",
            run_id=run_id, work_id=work_id, correlation_id=corr,
            actor_type="agent" if source == "agent" else "human",
            actor_id=actor,
            payload={"command_kind": command_kind, "source": source,
                     "goal_id": goal_id},
            idempotency_key=(f"{idempotency_key}:accepted"
                             if idempotency_key else None))
        return self._execute(run_id, work_id, corr, actor, source,
                             scope=(scope.data_scope,
                                    scope.test_run_id))

    def retry(self, run_id: str, *, actor: str) -> dict[str, Any]:
        run = self.store.get_business_run(run_id)
        if run is None:
            raise CommandGatewayError(f"run 不存在: {run_id}")
        if run["status"] != RUN_FAILED:
            raise CommandGatewayError(
                f"只有 failed run 可重试，当前 {run['status']}")
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="run.retried",
            run_id=run_id, work_id=run["work_id"],
            correlation_id=run["correlation_id"],
            actor_type="human", actor_id=actor, payload={})
        self.store.set_business_run_status(run_id, "running", error="")
        self.store.set_work_item_v2_status(run["work_id"], "running",
                                           blockers=[])
        return self._execute(run_id, run["work_id"],
                             run["correlation_id"], actor,
                             json.loads(run.get("params_json") or "{}")
                             .get("source", "api"),
                             params=json.loads(run.get("params_json") or "{}"),
                             images=self._replay_images.get(run_id),
                             scope=(run.get("data_scope") or "operational",
                                    run.get("test_run_id") or ""))

    def cancel(self, run_id: str, *, actor: str) -> dict[str, Any]:
        run = self.store.get_business_run(run_id)
        if run is None:
            raise CommandGatewayError(f"run 不存在: {run_id}")
        # 状态机：只有 queued/running 可取消；终态拒绝（诚实失败）
        self.store.set_business_run_status(run_id, "cancelled")
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="run.cancelled",
            run_id=run_id, work_id=run["work_id"],
            correlation_id=run["correlation_id"],
            actor_type="human", actor_id=actor, payload={})
        self.store.set_work_item_v2_status(run["work_id"], "cancelled")
        self.store.dispatch_outbox()
        return {"run_id": run_id, "status": "cancelled"}

    # ---------- 内部执行 ----------

    def _execute(self, run_id: str, work_id: str, corr: str,
                 actor: str, source: str,
                 params: dict[str, Any] | None = None,
                 images: list[tuple[str, bytes]] | None = None,
                 scope: tuple[str, str] = ("operational", ""),
                 ) -> dict[str, Any]:
        store = self.store
        run = store.get_business_run(run_id)
        params = params or json.loads(run.get("params_json") or "{}")
        images = (images or self._replay_images.get(run_id)
                  or self._decode_images(params.get("images", [])))
        store.set_business_run_status(
            run_id, "running", current_node="recognition")
        store.emit_event(
            event_id=_new_id("evt"), event_type="node.started",
            run_id=run_id, work_id=work_id, correlation_id=corr,
            actor_type="system", actor_id="recognition_node",
            payload={"node": "recognition"})
        try:
            out = run_recognition_batch(
                self.recognition_adapter, images,
                conf=float(params.get("conf", 0.25)), store=store,
                entry=params.get("entry", source if source != "web"
                                 else "single_file"),
                actor=actor,
                idempotency_key=None,  # run 幂等已在上层处理
                recognition_profile_id=params.get(
                    "recognition_profile_id", "production_legacy"),
                service_tier=params.get("service_tier", "standard"),
                source=source, project_id=params.get("project_id", ""),
                profiles_service=self.profiles_service,
                run_id=run_id, work_id=work_id, correlation_id=corr)
        except Exception as e:  # 失败留在同一 run：错误可见、可重试
            detail = getattr(e, "detail", None)
            msg = json.dumps(detail, ensure_ascii=False) \
                if isinstance(detail, dict) else str(e)
            store.set_business_run_status(run_id, "failed", error=msg,
                                          current_node="recognition")
            store.emit_event(
                event_id=_new_id("evt"), event_type="run.failed",
                run_id=run_id, work_id=work_id, correlation_id=corr,
                actor_type="system", actor_id="recognition_node",
                payload={"error": msg})
            store.set_work_item_v2_status(work_id, "blocked", blockers=[msg])
            store.dispatch_outbox()
            return {"run_id": run_id, "work_id": work_id,
                    "status": "failed", "error": msg, "result": None}

        task = out["task"]
        task_id = task["task_id"]
        # 用量：真实计量（按照片 + 实际计算时长），immutable 账本；
        # customer/project 作用域随 run 继承（G4 隔离依据）
        evidence_ref = f"recognition_task:{task_id}"
        store.insert_usage_event_v2(
            usage_id=_new_id("usage"), unit="recognition_photo",
            quantity=int(task.get("file_count") or 0), run_id=run_id,
            work_id=work_id, node="recognition",
            capability="vision.recognition.create",
            profile_id=out.get("recognition_profile_id", ""),
            tier=out.get("service_tier", ""),
            customer_id=run.get("customer_id", ""),
            project_id=run.get("project_id", ""),
            source_evidence=evidence_ref,
            data_scope=scope[0], test_run_id=scope[1])
        store.insert_usage_event_v2(
            usage_id=_new_id("usage"), unit="model_compute_ms",
            quantity=float(out.get("elapsed_ms") or 0), run_id=run_id,
            work_id=work_id, node="recognition",
            capability="vision.recognition.create",
            profile_id=out.get("recognition_profile_id", ""),
            tier=out.get("service_tier", ""),
            customer_id=run.get("customer_id", ""),
            project_id=run.get("project_id", ""),
            source_evidence=evidence_ref,
            data_scope=scope[0], test_run_id=scope[1])
        # 证据 bundle：输入 hash + 产物引用 + 生成者/配置版本
        input_hash = hashlib.sha256(json.dumps(
            [[n, hashlib.sha256(d).hexdigest()] for n, d in images],
            sort_keys=True).encode()).hexdigest()
        evidence = store.insert_evidence_bundle(
            evidence_id=_new_id("evid"), kind="recognition_result",
            run_id=run_id, work_id=work_id, source_uri=evidence_ref,
            content_type="application/json",
            producer="vision.recognition@" + str(
                out.get("recognition_profile_id")),
            input_hash=input_hash,
            config_version="tier=" + str(out.get("service_tier")),
            data_scope=scope[0], test_run_id=scope[1])
        status = "succeeded" if task["status"] == "completed" else "failed"
        store.set_business_run_status(
            run_id, status, current_node="recognition",
            subject_type="recognition_task", subject_id=task_id,
            evidence_bundle_id=evidence["evidence_id"],
            error="; ".join(out.get("errors") or []))
        store.emit_event(
            event_id=_new_id("evt"), event_type="node.completed",
            run_id=run_id, work_id=work_id, correlation_id=corr,
            actor_type="system", actor_id="recognition_node",
            subject_type="recognition_task", subject_id=task_id,
            payload={"sku_count": task.get("sku_count"),
                     "trace_id": out.get("trace_id"),
                     "evidence_bundle_id": evidence["evidence_id"]})
        store.emit_event(
            event_id=_new_id("evt"),
            event_type="run.succeeded" if status == "succeeded"
            else "run.failed",
            run_id=run_id, work_id=work_id, correlation_id=corr,
            actor_type="system", actor_id="recognition_node",
            subject_type="recognition_task", subject_id=task_id,
            payload={"task_id": task_id})
        store.set_work_item_v2_status(
            work_id, "done" if status == "succeeded" else "blocked",
            subject_type="recognition_task", subject_id=task_id)
        store.dispatch_outbox()
        store.rebuild_work_projection()
        return {"run_id": run_id, "work_id": work_id, "status": status,
                "result": {"task_id": task_id,
                           "trace_id": out.get("trace_id"),
                           "profile_id": out.get(
                               "recognition_profile_id"),
                           "evidence_bundle_id": evidence["evidence_id"]}}

    # ---------- 工具 ----------

    @staticmethod
    def _decode_images(raw: list) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise CommandGatewayError("images 必须为 [name, bytes|b64] 对")
            name, data = item
            if isinstance(data, str):
                try:
                    data = base64.b64decode(data, validate=True)
                except Exception:
                    data = data.encode("utf-8")
            out.append((str(name), bytes(data)))
        if not out:
            raise CommandGatewayError("images 不得为空")
        return out

    def _result_from_run(self, run: dict[str, Any]) -> dict | None:
        if not run.get("subject_id"):
            return None
        return {"task_id": run["subject_id"],
                "evidence_bundle_id": run.get("evidence_bundle_id")}
