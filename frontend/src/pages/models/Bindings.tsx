/**
 * 模型管理 · 能力分配（/models/bindings）——M9 交互层。
 *
 * 合同（04 §3.3）：
 * —— 校验返回影响预览：受影响对象、索引重建需求、回滚目标；
 * —— canary 必须带明确 scope（空 scope 后端拒绝）；
 * —— Agent 行由 Agent Definition 投影（本表只含受管绑定）；
 * —— 批准动作仅 release.approve 权限且非创建者可见（后端强制
 *    maker≠checker）；空态诚实。
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiTable } from "@/components/data/ApiTable";
import type { ApiTableCol } from "@/components/data/ApiTable";
import { ErrorState } from "@/components/data/ErrorState";
import { NeedLoginState } from "@/components/data/NeedLogin";
import { PageHeader } from "@/components/data/PageHeader";
import { StatusBadge } from "@/components/data/StatusBadge";
import type { StatusKind } from "@/components/data/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ApiError, fetchModelBindings, fetchModelCatalog, fetchModelConnections, postModelJson } from "@/lib/api";
import type { ModelBindingView } from "@/lib/api";
import { useAuth } from "@/store/auth";

function statusKind(status: string): StatusKind {
  switch (status) {
    case "active":
      return "good";
    case "pending_approval":
    case "canary":
    case "validated":
      return "warn";
    case "rejected":
    case "failed":
    case "disabled":
    case "rolled_back":
      return "serious";
    default:
      return "neutral";
  }
}

export default function Bindings() {
  const scopes = useAuth((s) => s.scopes);
  const me = useAuth((s) => s.me);
  const canApprove = useMemo(
    () => Boolean(scopes?.includes("models.release.approve")),
    [scopes],
  );
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<ModelBindingView[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<{ kind: StatusKind; text: string } | null>(null);
  const [impact, setImpact] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({
    binding_id: "", subject_kind: "module", subject_id: "",
    capability: "embedding", customer_id: "", project_id: "",
    connection_id: "", model_id: "",
  });
  const [catalog, setCatalog] = useState<Array<{
    connection_id: string; connection_version: number; model_id: string;
  }>>([]);
  const [connections, setConnections] = useState<Array<{
    connection_id: string; version: number; active_version?: number | null;
  }>>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [b, cat, conns] = await Promise.all([
        fetchModelBindings(), fetchModelCatalog(), fetchModelConnections(),
      ]);
      setRows(b.bindings);
      setCatalog(cat.entries.filter((e) => e.probe_status === "ready")
        .map((e) => ({ connection_id: e.connection_id,
                       connection_version: e.connection_version,
                       model_id: e.model_id })));
      setConnections(conns.connections.map((c) => ({
        connection_id: c.connection_id, version: c.version,
        active_version: c.active_version,
      })));
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const describeError = (e: unknown): string =>
    e instanceof ApiError ? `${e.status}: ${e.message}` : String(e);

  const call = useCallback(async (
    fn: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    setNotice(null);
    try {
      await fn();
      setNotice({ kind: "good", text: okText });
      await load();
    } catch (e) {
      setNotice({ kind: "serious", text: describeError(e) });
    } finally {
      setBusy(false);
    }
  }, [load]);

  const createDraft = useCallback(() => void call(async () => {
    const conn = connections.find((c) => c.connection_id === draft.connection_id);
    const entry = catalog.find(
      (c) => c.connection_id === draft.connection_id
          && c.model_id === draft.model_id);
    await postModelJson("bindings/drafts", {
      binding_id: draft.binding_id || undefined,
      subject_kind: draft.subject_kind,
      subject_id: draft.subject_id,
      capability: draft.capability,
      customer_id: draft.customer_id,
      project_id: draft.project_id,
      connection_id: draft.connection_id,
      connection_version: entry?.connection_version
        ?? conn?.active_version ?? conn?.version ?? 1,
      model_id: draft.model_id,
    }, "create binding draft");
  }, "绑定草稿已创建"), [call, catalog, connections, draft]);

  const validate = useCallback((row: ModelBindingView) => void call(async () => {
    const r = await postModelJson<{ impact: Record<string, unknown> }>(
      `bindings/${row.binding_id}/versions/${row.version}/validate`,
      {}, "validate binding");
    setImpact(r.impact ?? {});
  }, "校验通过（影响预览已更新）"), [call]);

  const withApproval = (row: ModelBindingView, action: string,
                        extra: Record<string, unknown> = {}) => void call(
    async () => {
      const approvalId = window.prompt("approval_id（治理账本）");
      if (!approvalId) throw new ApiError(400, "缺少 approval_id");
      await postModelJson(
        `bindings/${row.binding_id}/versions/${row.version}/${action}`,
        { approval_id: approvalId, ...extra }, `binding ${action}`);
    }, `操作成功：${action}`);

  const rollback = useCallback((row: ModelBindingView) => void call(
    async () => {
      const toVersion = window.prompt("回滚目标版本（已批准历史版本）");
      const approvalId = window.prompt("approval_id（回滚审批）");
      if (!toVersion || !approvalId) throw new ApiError(400, "缺少参数");
      await postModelJson(`bindings/${row.binding_id}/rollback`, {
        to_version: Number(toVersion), approval_id: approvalId,
      }, "binding rollback");
    }, "回滚成功"), [call]);

  const status = error instanceof ApiError ? error.status : 0;

  const cols: ApiTableCol<ModelBindingView>[] = [
    {
      key: "subject_id",
      label: "对象",
      render: (row) => `${row.subject_kind}:${row.subject_id}`,
    },
    { key: "capability", label: "能力" },
    {
      key: "connection_id",
      label: "Connection / Model",
      render: (row) =>
        `${row.connection_id}@v${row.connection_version} · ${row.model_id}`,
    },
    {
      key: "customer_id",
      label: "作用域",
      render: (row) =>
        [row.customer_id ? `客户 ${row.customer_id}` : "",
         row.project_id ? `项目 ${row.project_id}` : ""]
          .filter(Boolean).join(" / ") || "租户默认",
    },
    { key: "version", label: "版本", align: "right", render: (r) => `v${r.version}` },
    {
      key: "status",
      label: "状态",
      render: (row) => (
        <StatusBadge kind={statusKind(row.status)}>{row.status}</StatusBadge>
      ),
    },
    {
      key: "binding_id",
      label: "操作",
      render: (row) => (
        <span className="flex flex-wrap gap-1">
          {row.status === "draft" && (
            <>
              <Button size="sm" variant="secondary" disabled={busy}
                      data-testid="validate-binding"
                      onClick={() => validate(row)}>校验</Button>
              <Button size="sm" variant="secondary" disabled={busy}
                      onClick={() => void call(
                        () => postModelJson(
                          `bindings/${row.binding_id}/versions/${row.version}/submit`,
                          {}, "submit binding"),
                        "已提交审批")}>提交</Button>
            </>
          )}
          {row.status === "pending_approval" && canApprove
            && row.created_by !== me?.actor && (
            <>
              <Button size="sm" variant="secondary" disabled={busy}
                      data-testid="approve-binding"
                      onClick={() => withApproval(row, "approve")}>
                批准记录
              </Button>
              <Button size="sm" variant="secondary" disabled={busy}
                      onClick={() => withApproval(row, "activate-canary")}>
                Canary
              </Button>
              <Button size="sm" variant="secondary" disabled={busy}
                      onClick={() => withApproval(row, "activate")}>
                全量激活
              </Button>
            </>
          )}
          {(row.status === "active" || row.status === "superseded")
            && canApprove && (
            <Button size="sm" variant="secondary" disabled={busy}
                    data-testid="rollback-binding"
                    onClick={() => rollback(row)}>回滚</Button>
          )}
        </span>
      ),
    },
  ];

  return (
    <section className="flex h-full flex-col gap-3 p-4">
      <PageHeader
        title="能力分配"
        desc="系统能力 / 模块的版本化绑定；Agent 模型事实源仍是 Agent Definition"
        aside={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            刷新
          </Button>
        }
      />
      {notice && (
        <div role="status" className="text-xs">
          <StatusBadge kind={notice.kind}>{notice.text}</StatusBadge>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 rounded border border-line bg-surface p-3 md:grid-cols-4"
           data-testid="binding-form">
        <Input placeholder="binding_id（可空，自动派生）"
               value={draft.binding_id}
               onChange={(e) => setDraft({ ...draft, binding_id: e.target.value })} />
        <Select value={draft.subject_kind}
                onChange={(e) => setDraft({ ...draft, subject_kind: e.target.value })}>
          <option value="module">module（业务模块）</option>
          <option value="system_capability">system_capability（能力默认）</option>
        </Select>
        <Input placeholder="subject_id（如 research-rag / embedding）"
               value={draft.subject_id}
               onChange={(e) => setDraft({ ...draft, subject_id: e.target.value })} />
        <Select value={draft.capability}
                onChange={(e) => setDraft({ ...draft, capability: e.target.value })}>
          {["embedding", "chat", "reasoning", "vision", "ocr_text",
            "ocr_boxes", "rerank"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </Select>
        <Input placeholder="customer_id（可空=租户默认）"
               value={draft.customer_id}
               onChange={(e) => setDraft({ ...draft, customer_id: e.target.value })} />
        <Input placeholder="project_id（可空）" value={draft.project_id}
               onChange={(e) => setDraft({ ...draft, project_id: e.target.value })} />
        <Select value={draft.model_id} data-testid="select-model"
                onChange={(e) => {
                  const entry = catalog.find((c) => `${c.connection_id}/${c.model_id}` === e.target.value);
                  setDraft({
                    ...draft,
                    model_id: entry?.model_id ?? "",
                    connection_id: entry?.connection_id ?? "",
                  });
                }}>
          <option value="">选择模型（仅已探针通过）…</option>
          {catalog.map((c) => (
            <option key={`${c.connection_id}/${c.model_id}`}
                    value={`${c.connection_id}/${c.model_id}`}>
              {c.connection_id} · {c.model_id}
            </option>
          ))}
        </Select>
        <Button size="sm" disabled={busy || !draft.subject_id || !draft.model_id}
                data-testid="create-binding" onClick={createDraft}>
          新建绑定草稿
        </Button>
      </div>
      {impact && (
        <div className="rounded border border-line bg-surface p-3 text-xs"
             data-testid="impact-preview">
          <p className="font-semibold text-text-primary">影响预览（校验返回）</p>
          <ul className="mt-1 list-disc pl-4 text-text-secondary">
            <li>受影响对象：{String(impact.affected_subject ?? "—")}</li>
            <li>替换现有绑定：{String(impact.replaces ?? "无")}</li>
            <li>
              索引重建：
              {impact.index_rebuild_required
                ? "需要（embedding 身份变化，必须重建并评测后切换）"
                : "不需要"}
            </li>
            <li>回滚目标：{String(impact.rollback_target ?? "无")}</li>
          </ul>
        </div>
      )}
      {status === 401 ? (
        <NeedLoginState onOpenLogin={() => undefined} />
      ) : status === 403 ? (
        <ErrorState message="无模型管理权限" />
      ) : error ? (
        <ErrorState message={describeError(error)} onRetry={() => void load()} />
      ) : (
        <ApiTable rows={rows} cols={cols} loading={loading}
                  emptyText="暂无绑定"
                  rowKey={(r) => `${r.binding_id}@v${r.version}`} />
      )}
    </section>
  );
}
