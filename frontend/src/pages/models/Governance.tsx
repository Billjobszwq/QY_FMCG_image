/**
 * 模型管理 · 运行治理（/models/governance）——M9 交互层。
 *
 * 合同（04 §3.4）：顶部必要指标（请求量 / 诚实计量单位 / p95 /
 * 错误率 / 预算），下方用量趋势、连接健康、告警、审计。
 * 指标来自真实 usage 账本；无数据诚实标注（本地模型成本无价格表
 * 时显示“未知”，不伪装零成本）。
 */
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/data/ErrorState";
import { NeedLoginState } from "@/components/data/NeedLogin";
import { PageHeader } from "@/components/data/PageHeader";
import { StatusBadge } from "@/components/data/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  fetchModelAlerts,
  fetchModelConnections,
  fetchModelUsageSummary,
  fetchModelUsageTimeseries,
} from "@/lib/api";
import type { ModelConnectionView } from "@/lib/api";

interface UsageSummary {
  requests?: number;
  units?: Record<string, number>;
  errors?: {
    total_calls?: number;
    error_rate?: number;
    rate_limited_429?: number;
    metering_incomplete?: number;
  };
  latency_ms?: { p50?: number | null; p95?: number | null };
  cost?: { status?: string; resource_cost?: number };
  budgets?: Array<{
    budget_id: string; unit: string; period: string;
    consumed?: number; hard_limit?: number; utilization?: number;
  }>;
}

function fmt(v: unknown): string {
  if (typeof v === "number") return v.toLocaleString();
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

export default function Governance() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [alerts, setAlerts] = useState<Array<Record<string, unknown>>>([]);
  const [connections, setConnections] = useState<ModelConnectionView[]>([]);
  const [timeseries, setTimeseries] = useState<Array<Record<string, unknown>>>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, a, c, ts] = await Promise.all([
        fetchModelUsageSummary(),
        fetchModelAlerts(),
        fetchModelConnections(),
        fetchModelUsageTimeseries(24),
      ]);
      setSummary(s as UsageSummary);
      setAlerts(a.alerts);
      setConnections(c.connections);
      setTimeseries(ts.buckets);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const status = error instanceof ApiError ? error.status : 0;
  const units = summary?.units ?? {};
  const errors = summary?.errors ?? {};
  const latency = summary?.latency_ms ?? {};
  const cost = summary?.cost ?? {};
  const budgets = summary?.budgets ?? [];

  const kpis: Array<{ label: string; value: string }> = [
    { label: "请求量（24h）", value: fmt(summary?.requests) },
    { label: "输入 tokens", value: fmt(units.input_token) },
    { label: "输出 tokens", value: fmt(units.output_token) },
    { label: "Embedding 条目", value: fmt(units.embedding_input) },
    { label: "p95 延迟", value: latency.p95 != null ? `${latency.p95} ms` : "—" },
    {
      label: "错误率",
      value: errors.total_calls
        ? `${((errors.error_rate ?? 0) * 100).toFixed(1)}%（429：${errors.rate_limited_429 ?? 0}）`
        : "—",
    },
    {
      label: "成本",
      value: cost.status === "unknown"
        ? "未知（无价格表，不记为零成本）"
        : fmt(cost.resource_cost),
    },
    {
      label: "计量不完整",
      value: fmt(errors.metering_incomplete),
    },
  ];

  return (
    <section className="flex h-full flex-col gap-3 p-4">
      <PageHeader
        title="运行治理"
        desc="账号级用量 / 预算 / 告警 / 审计（数据来自 usage 账本）"
        aside={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            刷新
          </Button>
        }
      />
      {status === 401 ? (
        <NeedLoginState onOpenLogin={() => undefined} />
      ) : status === 403 ? (
        <ErrorState message="无模型用量读取权限" />
      ) : error ? (
        <ErrorState
          message={error instanceof Error ? error.message : undefined}
          onRetry={() => void load()}
        />
      ) : loading ? (
        <StatusBadge kind="neutral">加载中…</StatusBadge>
      ) : (
        <div className="flex flex-col gap-3 overflow-y-auto">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4"
               data-testid="governance-kpis">
            {kpis.map((k) => (
              <div key={k.label}
                   className="rounded border border-line bg-surface px-3 py-2">
                <p className="text-xs text-text-secondary">{k.label}</p>
                <p className="mt-1 text-sm font-semibold tabular-nums text-text-primary">
                  {k.value}
                </p>
              </div>
            ))}
          </div>

          <div data-testid="budget-panel">
            <h2 className="text-sm font-semibold text-text-primary">预算</h2>
            {budgets.length === 0 ? (
              <p className="mt-1 text-xs text-text-secondary">
                暂无预算配置
              </p>
            ) : (
              <ul className="mt-1 grid grid-cols-1 gap-1 md:grid-cols-2">
                {budgets.map((b) => (
                  <li key={b.budget_id} className="text-xs text-text-secondary">
                    {b.unit}/{b.period}：{fmt(b.consumed)} / {fmt(b.hard_limit)}
                    （{((b.utilization ?? 0) * 100).toFixed(1)}%）
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div data-testid="usage-trend">
            <h2 className="text-sm font-semibold text-text-primary">
              用量趋势（24h，小时桶）
            </h2>
            {timeseries.length === 0 ? (
              <p className="mt-1 text-xs text-text-secondary">暂无用量</p>
            ) : (
              <ul className="mt-1 max-h-40 overflow-y-auto text-xs text-text-secondary">
                {timeseries.map((t, i) => (
                  <li key={String(t.bucket_start ?? i)} className="tabular-nums">
                    {String(t.bucket_start).slice(11, 16)} ·
                    请求 {fmt(t.model_request)} ·
                    输入 {fmt(t.input_token)} ·
                    输出 {fmt(t.output_token)} ·
                    embed {fmt(t.embedding_input)}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div data-testid="connection-health">
            <h2 className="text-sm font-semibold text-text-primary">
              Provider / 连接状态
            </h2>
            {connections.length === 0 ? (
              <p className="mt-1 text-xs text-text-secondary">暂无连接</p>
            ) : (
              <ul className="mt-1 flex flex-col gap-1">
                {connections.map((c) => (
                  <li key={c.connection_id} className="flex items-center gap-2 text-xs">
                    <StatusBadge
                      kind={c.status === "active" ? "good" : c.status === "disabled" ? "serious" : "neutral"}>
                      {String(c.status)}
                    </StatusBadge>
                    <span className="text-text-secondary">
                      {c.name}（{c.location} / {c.adapter_kind}）
                      {c.active_version ? ` · active v${c.active_version}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div data-testid="alerts-panel">
            <h2 className="text-sm font-semibold text-text-primary">告警</h2>
            {alerts.length === 0 ? (
              <p className="mt-1 text-xs text-text-secondary">暂无告警</p>
            ) : (
              <ul className="mt-1 flex flex-col gap-1">
                {alerts.map((a, i) => (
                  <li key={String(a.alert_id ?? i)} className="text-xs text-text-secondary">
                    [{String(a.severity)}] {String(a.content)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
