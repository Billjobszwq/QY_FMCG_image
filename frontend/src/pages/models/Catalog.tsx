/**
 * 模型管理 · 模型目录（/models/catalog）——M9 交互层。
 *
 * 合同（04 §3.2）：发现模型 / 人工登记 / 能力探针；能力徽章只显示
 * probe 通过项，不得根据模型名猜测能力；空态诚实。
 */
import { useCallback, useEffect, useState } from "react";

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
import { ApiError, fetchModelCatalog, fetchModelConnections, postModelJson } from "@/lib/api";
import type { ModelCatalogView, ModelConnectionView } from "@/lib/api";

function probeKind(status: string): StatusKind {
  switch (status) {
    case "ready":
      return "good";
    case "probing":
      return "warn";
    case "failed":
      return "serious";
    default:
      return "neutral";
  }
}

export default function Catalog() {
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<ModelCatalogView[]>([]);
  const [connections, setConnections] = useState<ModelConnectionView[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<{ kind: StatusKind; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState({
    connection_id: "", model_id: "", capability: "embedding",
    embedding_dimension: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cat, conns] = await Promise.all([
        fetchModelCatalog(), fetchModelConnections(),
      ]);
      setRows(cat.entries);
      setConnections(conns.connections);
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

  const discover = useCallback(async (conn: ModelConnectionView) => {
    setBusy(true);
    setNotice(null);
    try {
      const r = await postModelJson<{ count: number }>(
        `connections/${conn.connection_id}/versions/${conn.version}/discover`,
        {}, "discover models");
      setNotice({ kind: "good", text: `发现 ${r.count} 个模型（待探针确认能力）` });
      await load();
    } catch (e) {
      setNotice({ kind: "serious", text: describeError(e) });
    } finally {
      setBusy(false);
    }
  }, [load]);

  const registerManual = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    try {
      const conn = connections.find((c) => c.connection_id === manual.connection_id);
      const body: Record<string, unknown> = {
        connection_id: manual.connection_id,
        connection_version: conn?.active_version ?? conn?.version ?? 1,
        model_id: manual.model_id,
        capabilities: [manual.capability],
      };
      if (manual.embedding_dimension) {
        body.embedding_dimension = Number(manual.embedding_dimension);
      }
      await postModelJson("catalog/manual", body, "register manual model");
      setNotice({ kind: "good", text: "已登记（仍需探针通过才能绑定）" });
      await load();
    } catch (e) {
      setNotice({ kind: "serious", text: describeError(e) });
    } finally {
      setBusy(false);
    }
  }, [connections, manual, load]);

  const probe = useCallback(async (row: ModelCatalogView) => {
    setBusy(true);
    setNotice(null);
    try {
      const r = await postModelJson<{ probe_status: string }>(
        `catalog/${row.catalog_id}/probe`, {}, "probe model");
      setNotice({
        kind: r.probe_status === "ready" ? "good" : "serious",
        text: `探针结果：${r.probe_status}`,
      });
      await load();
    } catch (e) {
      setNotice({ kind: "serious", text: describeError(e) });
    } finally {
      setBusy(false);
    }
  }, [load]);

  const status = error instanceof ApiError ? error.status : 0;

  const cols: ApiTableCol<ModelCatalogView>[] = [
    { key: "model_id", label: "模型 ID" },
    {
      key: "connection_id",
      label: "Connection",
      render: (row) => `${row.connection_id}@v${row.connection_version}`,
    },
    {
      key: "capabilities",
      label: "已验证能力",
      render: (row) =>
        row.probe_status === "ready" && row.capabilities.length > 0
          ? row.capabilities.map((c) => (
              <StatusBadge key={c} kind="good">{c}</StatusBadge>
            ))
          : <span className="text-text-secondary">—（探针未通过）</span>,
    },
    { key: "embedding_dimension", label: "维度", align: "right" },
    { key: "source", label: "来源" },
    {
      key: "probe_status",
      label: "Probe",
      render: (row) => (
        <StatusBadge kind={probeKind(row.probe_status)}>
          {row.probe_status}
        </StatusBadge>
      ),
    },
    {
      key: "last_verified_at",
      label: "操作",
      render: (row) => (
        <Button size="sm" variant="secondary" disabled={busy}
                data-testid="probe-model" onClick={() => void probe(row)}>
          探针
        </Button>
      ),
    },
  ];

  return (
    <section className="flex h-full flex-col gap-3 p-4">
      <PageHeader
        title="模型目录"
        desc="发现 / 人工登记 / 能力探针；能力以探针为准，不按模型名猜测"
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
      <div className="flex flex-wrap items-end gap-2 rounded border border-line bg-surface p-3"
           data-testid="catalog-actions">
        <label className="text-xs text-text-secondary">
          连接
          <Select value={manual.connection_id}
                  data-testid="select-connection"
                  onChange={(e) => setManual({ ...manual, connection_id: e.target.value })}>
            <option value="">选择连接…</option>
            {connections.map((c) => (
              <option key={c.connection_id} value={c.connection_id}>
                {c.name}（{c.connection_id}）
              </option>
            ))}
          </Select>
        </label>
        <Button size="sm" variant="secondary" disabled={busy || !manual.connection_id}
                data-testid="discover-models"
                onClick={() => {
                  const conn = connections.find(
                    (c) => c.connection_id === manual.connection_id);
                  if (conn) void discover(conn);
                }}>
          发现模型
        </Button>
        <span className="mx-2 border-l border-line self-stretch" />
        <Input placeholder="模型 ID" value={manual.model_id}
               data-testid="field-model-id" className="w-48"
               onChange={(e) => setManual({ ...manual, model_id: e.target.value })} />
        <Select value={manual.capability} className="w-36"
                onChange={(e) => setManual({ ...manual, capability: e.target.value })}>
          {["embedding", "chat", "reasoning", "vision", "ocr_text",
            "ocr_boxes", "rerank"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </Select>
        <Input placeholder="维度（可选）" value={manual.embedding_dimension}
               className="w-28" type="number"
               onChange={(e) => setManual({ ...manual, embedding_dimension: e.target.value })} />
        <Button size="sm" disabled={busy || !manual.connection_id || !manual.model_id}
                data-testid="register-manual" onClick={() => void registerManual()}>
          人工登记
        </Button>
      </div>
      {status === 401 ? (
        <NeedLoginState onOpenLogin={() => undefined} />
      ) : status === 403 ? (
        <ErrorState message="无模型管理权限" />
      ) : error ? (
        <ErrorState message={describeError(error)} onRetry={() => void load()} />
      ) : (
        <ApiTable rows={rows} cols={cols} loading={loading}
                  emptyText="暂无模型" rowKey={(r) => r.catalog_id} />
      )}
    </section>
  );
}
