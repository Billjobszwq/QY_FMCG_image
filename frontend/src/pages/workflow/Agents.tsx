/**
 * Agent 矩阵（/workflow/agents）—— 版本化 Agent 注册表 + 平台 Capability 目录（瘦版重实现）。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— GET /api/v1/agents（agent_id / version / domain / risk_level）
 * —— GET /api/v1/capabilities（模块能力目录：fail-closed，未注册不可调用）
 *
 * 本页只读：定义编辑 / 发布 / 回滚等高风险写操作不在本页直连。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, fetchAgents, fetchCapabilities } from "@/lib/api";
import type { AgentInfo, CapabilityInfo } from "@/lib/api";
import {
  ApiTable,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { Button } from "@/components/ui/button";

/* ============================================================================
   小工具（页面内私有）
   ========================================================================== */

/** 请求桌面层打开登录窗口。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

/** 风险等级 → StatusBadge（状态保留色纪律：低=good / 中=warn / 高=serious）。 */
const RISK_CN: Record<string, { kind: StatusKind; text: string }> = {
  low: { kind: "good", text: "低风险" },
  medium: { kind: "warn", text: "中风险" },
  high: { kind: "serious", text: "高风险" },
  critical: { kind: "serious", text: "极高风险" },
};

function riskBadge(level: string): ReactNode {
  const m = RISK_CN[level] ?? { kind: "neutral" as StatusKind, text: level };
  return <StatusBadge kind={m.kind}>{m.text}</StatusBadge>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-[13px] font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

/** 分布统计：{key: count} → “a × 1 · b × 2”。 */
function distribute(values: string[]): string {
  const acc: Record<string, number> = {};
  for (const v of values) acc[v] = (acc[v] ?? 0) + 1;
  const parts = Object.entries(acc).map(([k, n]) => `${k} × ${n}`);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Agents() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsErr, setAgentsErr] = useState<unknown>(null);
  const [agents401, setAgents401] = useState(false);

  const [caps, setCaps] = useState<CapabilityInfo[]>([]);
  const [capsLoading, setCapsLoading] = useState(true);
  const [capsErr, setCapsErr] = useState<unknown>(null);
  const [caps401, setCaps401] = useState(false);

  const loadAgents = useCallback(async () => {
    setAgentsLoading(true);
    setAgentsErr(null);
    setAgents401(false);
    try {
      setAgents((await fetchAgents()).agents);
    } catch (e) {
      if (is401(e)) setAgents401(true);
      else setAgentsErr(e);
    } finally {
      setAgentsLoading(false);
    }
  }, []);

  const loadCaps = useCallback(async () => {
    setCapsLoading(true);
    setCapsErr(null);
    setCaps401(false);
    try {
      setCaps((await fetchCapabilities()).capabilities);
    } catch (e) {
      if (is401(e)) setCaps401(true);
      else setCapsErr(e);
    } finally {
      setCapsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAgents();
    void loadCaps();
  }, [loadAgents, loadCaps]);

  const agentCols: ApiTableCol<AgentInfo>[] = [
    {
      key: "agent_id",
      label: "Agent",
      render: (a) => <span className="font-mono text-[13px]">{a.agent_id}</span>,
    },
    { key: "version", label: "版本" },
    { key: "domain", label: "领域" },
    { key: "risk_level", label: "风险等级", render: (a) => riskBadge(a.risk_level) },
  ];

  const capCols: ApiTableCol<CapabilityInfo>[] = [
    {
      key: "capability_id",
      label: "capability",
      render: (c) => <span className="font-mono text-xs text-text-secondary">{c.capability_id}</span>,
    },
    { key: "module_name", label: "模块" },
    { key: "module_version", label: "版本" },
    { key: "kind", label: "kind" },
    {
      key: "description",
      label: "描述",
      render: (c) => <span className="text-xs text-text-secondary">{c.description || "—"}</span>,
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="Agent 矩阵"
        desc="版本化 Agent 注册表与平台 Capability 目录（fail-closed：未注册即不可调用）"
        aside={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void loadAgents();
              void loadCaps();
            }}
          >
            刷新
          </Button>
        }
      />

      {/* ---- 概览 ---- */}
      {!agentsLoading && !agentsErr && !agents401 && !capsLoading && !capsErr && !caps401 && (
        <KV
          items={[
            { label: "注册 Agent", value: `${agents.length} 个` },
            { label: "Capability", value: `${caps.length} 项` },
            { label: "风险分布", value: distribute(agents.map((a) => a.risk_level)) },
            { label: "kind 分布", value: distribute(caps.map((c) => c.kind)) },
          ]}
        />
      )}

      {/* ---- Agent 注册表 ---- */}
      <Section title={`Agent 注册表（${agentsLoading ? "…" : agents.length}）`}>
        {agents401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <ApiTable
            rows={agents}
            cols={agentCols}
            rowKey={(a) => a.agent_id}
            loading={agentsLoading}
            error={agentsErr}
            onRetry={() => void loadAgents()}
            emptyText="暂无注册 Agent"
          />
        )}
      </Section>

      {/* ---- Capability 目录 ---- */}
      <Section title={`Capability 目录（${capsLoading ? "…" : caps.length}）`}>
        {caps401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <ApiTable
            rows={caps}
            cols={capCols}
            rowKey={(c) => c.capability_id}
            loading={capsLoading}
            error={capsErr}
            onRetry={() => void loadCaps()}
            emptyText="暂无已注册 Capability"
          />
        )}
      </Section>
    </div>
  );
}
