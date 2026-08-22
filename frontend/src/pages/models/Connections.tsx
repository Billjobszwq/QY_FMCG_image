/**
 * 模型管理 · 连接管理（/models/connections）——M9 交互层。
 *
 * 合同（04 §3.1）：
 * —— 新增/编辑受控表单：名称/位置/协议模板/Base URL/API Flavor/
 *    API Key（password，只写）/Timeout/Max retries；
 * —— 按钮：保存草稿 → 测试连接 → 申请启用；测试成功不改变 active；
 * —— 密钥字段提交后立即清空；列表只显示 已配置/版本/轮换时间；
 * —— maker 看不到批准自己变更的动作（后端仍强制 maker≠checker）；
 * —— 401/403/404/409/422/429/503 诚实状态；空态不填样本数据。
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
import { ApiError, fetchModelConnections, postModelJson } from "@/lib/api";
import type { ModelConnectionView } from "@/lib/api";
import { useAuth } from "@/store/auth";

function statusKind(status: string): StatusKind {
  switch (status) {
    case "ready":
    case "active":
      return "good";
    case "testing":
    case "pending_approval":
    case "canary":
      return "warn";
    case "rejected":
    case "failed":
    case "disabled":
      return "serious";
    default:
      return "neutral";
  }
}

interface DraftForm {
  name: string;
  location: "local" | "api";
  adapter_kind: "openai_compatible" | "anthropic";
  api_flavor: string;
  base_url: string;
  timeout_ms: number;
  max_retries: number;
  secret_value: string;
}

const EMPTY_FORM: DraftForm = {
  name: "",
  location: "local",
  adapter_kind: "openai_compatible",
  api_flavor: "chat_completions",
  base_url: "http://127.0.0.1:8455/v1",
  timeout_ms: 30000,
  max_retries: 1,
  secret_value: "",
};

export default function Connections() {
  const scopes = useAuth((s) => s.scopes);
  const me = useAuth((s) => s.me);
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<ModelConnectionView[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<DraftForm>(EMPTY_FORM);
  const [notice, setNotice] = useState<{ kind: StatusKind; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const canApprove = useMemo(
    () => Boolean(scopes?.includes("models.release.approve")),
    [scopes],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchModelConnections();
      setRows(d.connections);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const describeError = (e: unknown): string => {
    if (e instanceof ApiError) {
      switch (e.status) {
        case 409:
          return "版本冲突：请刷新后重试（你的草稿不会被覆盖）";
        case 422:
          return `输入不合法：${e.message}`;
        case 429:
          return "请求过于频繁，请稍后重试";
        case 503:
          return `服务不可用：${e.message}`;
        default:
          return e.message;
      }
    }
    return e instanceof Error ? e.message : "未知错误";
  };

  const saveDraft = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    try {
      const body: Record<string, unknown> = {
        name: form.name,
        location: form.location,
        adapter_kind: form.adapter_kind,
        api_flavor: form.api_flavor,
        base_url: form.base_url,
        timeout_ms: form.timeout_ms,
        max_retries: form.max_retries,
      };
      const r = await postModelJson<{
        connection_id: string;
        version: number;
        etag: string;
      }>("connections/drafts", body, "create connection draft");
      // 密钥只写：若填写了凭据，立即提交并清空输入
      if (form.secret_value) {
        await postModelJson(
          `connections/${r.connection_id}/versions/${r.version}/secret`,
          { secret_value: form.secret_value },
          "submit secret",
        );
        setForm((f) => ({ ...f, secret_value: "" }));
      }
      setNotice({ kind: "good", text: `草稿已保存：${r.connection_id}@v${r.version}` });
      setShowForm(false);
      setForm(EMPTY_FORM);
      await load();
    } catch (e) {
      setNotice({ kind: "serious", text: describeError(e) });
    } finally {
      setBusy(false);
    }
  }, [form, load]);

  const act = useCallback(
    async (row: ModelConnectionView, action: string, label: string,
           body: Record<string, unknown> = {}) => {
      setBusy(true);
      setNotice(null);
      try {
        await postModelJson(
          `connections/${row.connection_id}/versions/${row.version}/${action}`,
          body, label);
        setNotice({ kind: "good", text: `${row.connection_id}@v${row.version}：操作成功` });
        await load();
      } catch (e) {
        setNotice({ kind: "serious", text: describeError(e) });
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const approve = useCallback(
    async (row: ModelConnectionView) => {
      const approvalId = window.prompt("approval_id（治理账本）");
      if (!approvalId) return;
      await act(row, "approve", "approve connection",
                { approval_id: approvalId });
    },
    [act],
  );

  const rotateSecret = useCallback(
    async (row: ModelConnectionView) => {
      const value = window.prompt("新的 API Key（只写，提交后不回显）");
      if (!value) return;
      setBusy(true);
      setNotice(null);
      try {
        await postModelJson(
          `connections/${row.connection_id}/versions/${row.version}/secret`,
          { secret_value: value }, "rotate secret");
        setNotice({ kind: "good", text: "凭据已写入（不回显）" });
        await load();
      } catch (e) {
        setNotice({ kind: "serious", text: describeError(e) });
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const status = error instanceof ApiError ? error.status : 0;

  const cols: ApiTableCol<ModelConnectionView>[] = [
    { key: "name", label: "名称" },
    { key: "location", label: "位置" },
    { key: "adapter_kind", label: "协议" },
    { key: "base_url", label: "Base URL" },
    {
      key: "secret_configured",
      label: "凭据状态",
      render: (row) =>
        row.secret_configured ? (
          <span data-testid="secret-meta">
            已配置 · v{row.secret_version ?? "—"}
            {row.last_rotated_at
              ? ` · 轮换 ${row.last_rotated_at.slice(0, 10)}`
              : ""}
          </span>
        ) : (
          <span className="text-text-secondary">未配置</span>
        ),
    },
    {
      key: "status",
      label: "状态",
      render: (row) => (
        <StatusBadge kind={statusKind(row.status)}>{row.status}</StatusBadge>
      ),
    },
    {
      key: "active_version",
      label: "Active",
      align: "right",
      render: (row) => (row.active_version ? `v${row.active_version}` : "—"),
    },
    {
      key: "version",
      label: "操作",
      render: (row) => (
        <span className="flex flex-wrap gap-1">
          {(row.status === "draft" || row.status === "failed") && (
            <Button size="sm" variant="secondary" disabled={busy}
                    onClick={() => void act(row, "test", "test connection")}>
              测试
            </Button>
          )}
          {row.status === "ready" && (
            <Button size="sm" variant="secondary" disabled={busy}
                    onClick={() => void act(row, "submit", "submit connection")}>
              申请启用
            </Button>
          )}
          {row.status === "pending_approval" && canApprove
            && row.created_by !== me?.actor && (
            <Button size="sm" variant="secondary" disabled={busy}
                    data-testid="approve-connection"
                    onClick={() => void approve(row)}>
              批准
            </Button>
          )}
          {row.status === "active" && canApprove && (
            <Button size="sm" variant="secondary" disabled={busy}
                    onClick={() => void act(row, "disable", "disable connection")}>
              停用
            </Button>
          )}
          {row.status !== "active" && (
            <Button size="sm" variant="secondary" disabled={busy}
                    data-testid="rotate-secret"
                    onClick={() => void rotateSecret(row)}>
              轮换凭据
            </Button>
          )}
        </span>
      ),
    },
  ];

  return (
    <section className="flex h-full flex-col gap-3 p-4">
      <PageHeader
        title="连接管理"
        desc="统一管理本地与外部模型服务；仅授权角色可见"
        aside={
          <>
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              刷新
            </Button>
            <Button size="sm" onClick={() => setShowForm((v) => !v)}>
              新增连接
            </Button>
          </>
        }
      />
      {notice && (
        <div role="status" className="text-xs">
          <StatusBadge kind={notice.kind}>{notice.text}</StatusBadge>
        </div>
      )}
      {showForm && (
        <div className="grid grid-cols-2 gap-2 rounded border border-line bg-surface p-3 md:grid-cols-4"
             data-testid="connection-form">
          <label className="col-span-2 text-xs text-text-secondary">
            连接名称
            <Input value={form.name} data-testid="field-name"
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="text-xs text-text-secondary">
            位置
            <Select value={form.location}
                    onChange={(e) => setForm({ ...form, location: e.target.value as DraftForm["location"] })}>
              <option value="local">本地（local）</option>
              <option value="api">外部（api）</option>
            </Select>
          </label>
          <label className="text-xs text-text-secondary">
            Provider 模板
            <Select value={form.adapter_kind}
                    onChange={(e) => setForm({ ...form, adapter_kind: e.target.value as DraftForm["adapter_kind"] })}>
              <option value="openai_compatible">OpenAI-compatible / OMLX</option>
              <option value="anthropic">Anthropic 原生</option>
            </Select>
          </label>
          <label className="col-span-2 text-xs text-text-secondary">
            Base URL
            <Input value={form.base_url} data-testid="field-base-url"
                   onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          </label>
          <label className="text-xs text-text-secondary">
            API Flavor
            <Select value={form.api_flavor}
                    onChange={(e) => setForm({ ...form, api_flavor: e.target.value })}>
              <option value="chat_completions">chat_completions</option>
              <option value="responses">responses</option>
              <option value="auto">auto</option>
            </Select>
          </label>
          <label className="col-span-2 text-xs text-text-secondary">
            API Key（只写，保存后不回显）
            <Input type="password" value={form.secret_value}
                   data-testid="field-secret" autoComplete="off"
                   onChange={(e) => setForm({ ...form, secret_value: e.target.value })} />
          </label>
          <label className="text-xs text-text-secondary">
            Timeout (ms)
            <Input type="number" value={form.timeout_ms}
                   onChange={(e) => setForm({ ...form, timeout_ms: Number(e.target.value) })} />
          </label>
          <label className="text-xs text-text-secondary">
            Max retries
            <Input type="number" value={form.max_retries}
                   onChange={(e) => setForm({ ...form, max_retries: Number(e.target.value) })} />
          </label>
          <div className="col-span-2 flex gap-2 md:col-span-4">
            <Button size="sm" disabled={busy || !form.name}
                    data-testid="save-draft" onClick={() => void saveDraft()}>
              保存草稿
            </Button>
            <Button size="sm" variant="secondary"
                    onClick={() => { setShowForm(false); setForm(EMPTY_FORM); }}>
              取消
            </Button>
          </div>
        </div>
      )}
      {status === 401 ? (
        <NeedLoginState onOpenLogin={() => undefined} />
      ) : status === 403 ? (
        <ErrorState message="无模型管理权限" />
      ) : error ? (
        <ErrorState message={describeError(error)} onRetry={() => void load()} />
      ) : (
        <ApiTable
          rows={rows}
          cols={cols}
          loading={loading}
          emptyText="暂无连接"
          rowKey={(r) => `${r.connection_id}@v${r.version}`}
        />
      )}
    </section>
  );
}
