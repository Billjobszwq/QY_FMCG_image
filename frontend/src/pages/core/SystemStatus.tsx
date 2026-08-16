/**
 * 系统状态（P1 core/SystemStatus）。
 *
 * 数据源（全部同源 /api/v1/*，禁止样本数据）：
 * —— /api/v1/health：整体状态 + 依赖服务明细（ApiTable 呈现）；
 * —— /api/v1/version：平台与版本；
 * —— /api/v1/capabilities：已注册 Capability（Module Manifest）。
 *
 * 状态纪律：加载=HedgehogLoader（ApiTable 内置）；错误=ErrorState+重试；
 * 状态一律 StatusBadge（图标+文字）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  fetchCapabilities,
  fetchHealth,
  fetchVersion,
} from "@/lib/api";
import type { CapabilityInfo, HealthBody, ServiceStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatTile } from "@/components/charts/primitives";
import {
  ApiTable,
  KV,
  PageHeader,
  StatusBadge,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";

/** 健康状态 → StatusBadge。 */
function healthKind(status: string | undefined): StatusKind {
  if (status === "healthy") return "good";
  if (status === "degraded") return "warn";
  if (status === "unavailable") return "serious";
  return "neutral";
}

const HEALTH_CN: Record<string, string> = {
  healthy: "正常",
  degraded: "降级",
  unavailable: "不可用",
};

/** UTC ISO → 本地时间展示。 */
function fmtWhen(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return String(s).slice(0, 19);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/** 依赖服务明细列（数值右对齐、状态徽章化）。 */
const SERVICE_COLS: ApiTableCol<ServiceStatus>[] = [
  { key: "name", label: "服务" },
  {
    key: "status",
    label: "状态",
    render: (s) => (
      <StatusBadge kind={healthKind(s.status)}>
        {HEALTH_CN[s.status] ?? s.status}
      </StatusBadge>
    ),
  },
  {
    key: "critical",
    label: "关键",
    render: (s) =>
      s.critical ? (
        <span className="text-text-primary">关键</span>
      ) : (
        <span className="text-text-secondary">非关键</span>
      ),
  },
  {
    key: "latency_ms",
    label: "延迟",
    align: "right",
    render: (s) =>
      s.latency_ms === null || s.latency_ms === undefined
        ? "—"
        : `${s.latency_ms} ms`,
  },
  {
    key: "description",
    label: "说明",
    render: (s) => (
      <div className="min-w-48">
        <div className="text-text-primary">{s.description}</div>
        {s.detail && s.detail !== "ok" ? (
          <div className="text-xs text-text-secondary">{s.detail}</div>
        ) : null}
      </div>
    ),
  },
];

/** 已注册 Capability 列。 */
const CAPABILITY_COLS: ApiTableCol<CapabilityInfo>[] = [
  { key: "capability_id", label: "capability_id" },
  { key: "module_name", label: "模块" },
  { key: "module_version", label: "版本" },
  { key: "kind", label: "类型" },
  { key: "description", label: "说明" },
];

export default function SystemStatus() {
  const [health, setHealth] = useState<HealthBody | null>(null);
  const [version, setVersion] = useState<{
    platform: string;
    version: string;
  } | null>(null);
  const [caps, setCaps] = useState<CapabilityInfo[] | null>(null);
  const [healthErr, setHealthErr] = useState<unknown>(null);
  const [versionErr, setVersionErr] = useState<unknown>(null);
  const [capsErr, setCapsErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setHealthErr(null);
    setVersionErr(null);
    setCapsErr(null);
    const [h, v, c] = await Promise.allSettled([
      fetchHealth(),
      fetchVersion(),
      fetchCapabilities(),
    ]);
    if (h.status === "fulfilled") setHealth(h.value);
    else {
      setHealth(null);
      setHealthErr(h.reason);
    }
    if (v.status === "fulfilled") setVersion(v.value);
    else {
      setVersion(null);
      setVersionErr(v.reason);
    }
    if (c.status === "fulfilled") setCaps(c.value.capabilities);
    else {
      setCaps(null);
      setCapsErr(c.reason);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const services = health?.services ?? [];
  const countOf = (s: string) => services.filter((x) => x.status === s).length;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="系统状态"
        desc="服务健康 / 平台版本 / 已注册能力（实时读取，只读）"
        aside={
          <>
            {health && (
              <StatusBadge kind={healthKind(health.status)}>
                整体{HEALTH_CN[health.status] ?? health.status}
              </StatusBadge>
            )}
            <Button variant="secondary" size="sm" onClick={() => void load()}>
              刷新
            </Button>
          </>
        }
      />

      {/* 服务健康 KPI */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="依赖服务" value={services.length} note="health 实时探测" />
        <StatTile label="正常" value={countOf("healthy")} note="healthy" />
        <StatTile label="降级" value={countOf("degraded")} note="degraded" />
        <StatTile label="不可用" value={countOf("unavailable")} note="unavailable" />
      </div>

      {/* 平台信息（version + health 汇总） */}
      <section>
        <h2 className="mb-2 font-display text-sm font-bold text-text-primary">
          平台信息
        </h2>
        {versionErr && !version ? (
          <KV
            items={[
              {
                label: "平台",
                value: (
                  <StatusBadge kind="serious">版本信息加载失败</StatusBadge>
                ),
              },
            ]}
          />
        ) : (
          <KV
            items={[
              {
                label: "平台",
                value: version
                  ? `${version.platform} v${version.version}`
                  : "加载中…",
              },
              {
                label: "整体状态",
                value: health ? (
                  <StatusBadge kind={healthKind(health.status)}>
                    {HEALTH_CN[health.status] ?? health.status}
                  </StatusBadge>
                ) : (
                  <span className="text-text-secondary">加载中…</span>
                ),
              },
              {
                label: "检查时间",
                value: health ? fmtWhen(health.generated_at) : "—",
              },
              {
                label: "关键服务",
                value: health
                  ? `${services.filter((s) => s.critical).length} 个关键 / ${services.length} 个合计`
                  : "—",
              },
            ]}
          />
        )}
      </section>

      {/* 依赖服务明细 */}
      <section className="space-y-2">
        <h2 className="font-display text-sm font-bold text-text-primary">
          依赖服务明细
        </h2>
        <ApiTable<ServiceStatus>
          rows={services}
          cols={SERVICE_COLS}
          loading={loading && !health && !healthErr}
          error={healthErr}
          onRetry={() => void load()}
          emptyText="后端未返回任何服务项"
          rowKey={(s) => s.name}
        />
      </section>

      {/* 已注册 Capability */}
      <section className="space-y-2">
        <h2 className="font-display text-sm font-bold text-text-primary">
          已注册 Capability（Module Manifest）
        </h2>
        <ApiTable<CapabilityInfo>
          rows={caps ?? []}
          cols={CAPABILITY_COLS}
          loading={loading && !caps && !capsErr}
          error={capsErr}
          onRetry={() => void load()}
          emptyText="模块注册表为空"
          rowKey={(c) => c.capability_id}
        />
      </section>
    </div>
  );
}
