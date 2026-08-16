/**
 * 分析与 BI · 语义资产（P7）。
 *
 * 数据源（同源 /api/v1/*，禁假数据）：
 * —— /api/v1/capabilities：能力注册表（模块 / 版本 / kind，只读）；
 * —— /api/v1/usage/summary | rows | budgets | legacy：不可变 Usage 账本计量
 *    （按单位 / 按日趋势 / 项目预算 / 历史未归属归属账本）；
 * —— /api/v1/master/customers：客户筛选选项；
 * —— /api/v1/usage/reconcile-legacy：追加式对账（mutation，幂等 append-only）。
 *
 * usage/* 端点未在 typed client 中单列，走 fetchIamGet/fetchIamPost 通用通道
 * （同样自动补 /api/v1 前缀、附 CSRF 头）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchCapabilities,
  fetchIamGet,
  fetchIamPost,
} from "@/lib/api";
import type { CapabilityInfo } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import { ChartCard, HBars, VBars } from "@/components/charts/primitives";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { HedgehogLoader } from "@/components/ui/loader";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   usage 载荷类型（ABOSV3 T10：客户级 Usage 工作台契约）
   ========================================================================== */

interface UsageSummary {
  customer_id: string;
  by_unit: { unit: string; total: number; n: number }[];
  by_date: { day: string; n: number; total: number }[];
  anomalies: { day: string; count: number; avg: number; rule: string }[];
  unattributed: number;
  note: string;
}

interface UsageRow {
  usage_id: string;
  unit: string;
  quantity: number;
  run_id: string;
  work_id: string;
  capability: string;
  model: string;
  profile_id: string;
  tier: string;
  project_id: string;
  source_evidence: string;
  occurred_at: string;
  run_status: string | null;
  evidence_bundle_id: string | null;
  lineage: "attributed" | "legacy_unattributed";
}

interface BudgetRow {
  project_id: string;
  customer_id: string;
  name: string;
  budget_total: number | null;
  usage_events: number;
  note: string;
}

interface LegacyAttribution {
  attribution_id: string;
  usage_id: string;
  attribution_status: string;
  customer_id: string;
  project_id: string;
  note: string;
  created_by: string;
  created_at: string;
}

interface CustomerRow {
  customer_id: string;
  name: string;
}

/* ============================================================================
   登录窗口：401 → 打开登录窗口（桌面层幂等开窗）
   ========================================================================== */

function openLoginWindow(): void {
  const wm = useWindowManager.getState();
  wm.openWindow({
    id: "platform-login",
    title: "登录",
    content: (
      <LoginWindow
        onLoggedIn={() => useWindowManager.getState().closeWindow("platform-login")}
      />
    ),
    defaultPosition: { x: 240, y: 160 },
    defaultSize: { width: 380, height: 340 },
    resizable: false,
  });
}

/** ISO 时间 → MM-DD HH:mm。 */
function shortTime(iso: string): string {
  return iso && iso.length >= 16 ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : iso || "—";
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Semantics() {
  /* 能力注册表（公开端点） */
  const [caps, setCaps] = useState<CapabilityInfo[] | null>(null);
  const [capsErr, setCapsErr] = useState<unknown>(null);

  /* 客户筛选 */
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [customer, setCustomer] = useState("");

  /* usage 计量（需登录会话） */
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [rows, setRows] = useState<UsageRow[]>([]);
  const [budgets, setBudgets] = useState<BudgetRow[]>([]);
  const [legacy, setLegacy] = useState<LegacyAttribution[]>([]);
  const [usageErr, setUsageErr] = useState<unknown>(null);
  const [usageLoading, setUsageLoading] = useState(true);

  const [reconMsg, setReconMsg] = useState<string | null>(null);
  const [reconBusy, setReconBusy] = useState(false);

  const loadCaps = useCallback(async () => {
    setCapsErr(null);
    try {
      const d = await fetchCapabilities();
      setCaps(d.capabilities);
    } catch (e) {
      setCaps(null);
      setCapsErr(e);
    }
  }, []);

  const loadUsage = useCallback(async (customerId: string) => {
    setUsageLoading(true);
    setUsageErr(null);
    const cid = encodeURIComponent(customerId);
    try {
      const [s, r, b, l] = await Promise.all([
        fetchIamGet(`usage/summary?customer_id=${cid}`),
        fetchIamGet(`usage/rows?customer_id=${cid}&limit=50`),
        fetchIamGet(`usage/budgets?customer_id=${cid}`),
        fetchIamGet("usage/legacy"),
      ]);
      setSummary(s as UsageSummary);
      setRows(((r as { rows?: UsageRow[] }).rows ?? []));
      setBudgets(((b as { budgets?: BudgetRow[] }).budgets ?? []));
      setLegacy(((l as { attributions?: LegacyAttribution[] }).attributions ?? []));
    } catch (e) {
      setSummary(null);
      setUsageErr(e);
    } finally {
      setUsageLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCaps();
    /* 客户选项加载失败不阻塞：退回“全平台”单选项 */
    fetchIamGet("master/customers")
      .then((d) => setCustomers(((d as { customers?: CustomerRow[] }).customers ?? [])))
      .catch(() => setCustomers([]));
    void loadUsage("");
  }, [loadCaps, loadUsage]);

  const refresh = () => {
    void loadCaps();
    void loadUsage(customer);
  };

  /* 追加式对账：幂等 append-only，不篡改不可变 Usage */
  const reconcile = async () => {
    setReconBusy(true);
    setReconMsg(null);
    try {
      const out = (await fetchIamPost("usage/reconcile-legacy", {})) as {
        added: number;
        legacy_total: number;
      };
      setReconMsg(`已追加 ${out.added} 条归属记录（累计 ${out.legacy_total}）`);
      await loadUsage(customer);
    } catch (e) {
      setReconMsg(`对账失败：${errorMessageOf(e)}`);
    } finally {
      setReconBusy(false);
    }
  };

  const needLogin = usageErr instanceof ApiError && usageErr.status === 401;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="语义资产"
        desc="能力注册表 × 不可变 Usage 计量账本：只有注册能力产生计量，每行可下钻 run / 证据"
        aside={
          <>
            <Select
              className="h-8 w-40"
              aria-label="客户筛选"
              value={customer}
              onChange={(e) => {
                setCustomer(e.target.value);
                void loadUsage(e.target.value);
              }}
            >
              <option value="">全平台</option>
              {customers.map((c) => (
                <option key={c.customer_id} value={c.customer_id}>
                  {c.name || c.customer_id}
                </option>
              ))}
            </Select>
            <Button variant="secondary" size="sm" onClick={refresh}>
              刷新
            </Button>
            <Button variant="secondary" size="sm" asChild>
              <a
                href={`/api/v1/usage/export.csv?customer_id=${encodeURIComponent(customer)}`}
              >
                导出 CSV
              </a>
            </Button>
          </>
        }
      />

      {/* ---- 能力注册表（公开） ---- */}
      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <h3 className="font-display text-sm font-bold text-text-primary">
            能力注册表
          </h3>
          {caps && (
            <span className="text-xs text-text-secondary">
              {caps.length} 项注册能力
            </span>
          )}
        </div>
        {caps === null && capsErr ? (
          <ErrorState message={errorMessageOf(capsErr)} onRetry={() => void loadCaps()} />
        ) : (
          <ApiTable
            rows={caps ?? []}
            loading={caps === null}
            rowKey={(c) => c.capability_id}
            cols={[
              { key: "capability_id", label: "能力 ID" },
              {
                key: "module_name",
                label: "模块",
                render: (c) => (
                  <span>
                    {c.module_name}
                    <span className="ml-1 text-text-secondary">
                      v{c.module_version}
                    </span>
                  </span>
                ),
              },
              {
                key: "kind",
                label: "类型",
                render: (c) => (
                  <span className="text-text-secondary">{c.kind}</span>
                ),
              },
              { key: "description", label: "描述" },
            ]}
            emptyText="暂无注册能力"
          />
        )}
      </section>

      {/* ---- Usage 计量（需登录会话） ---- */}
      {needLogin ? (
        <NeedLoginState onOpenLogin={openLoginWindow} />
      ) : usageErr ? (
        <ErrorState message={errorMessageOf(usageErr)} onRetry={refresh} />
      ) : usageLoading && !summary ? (
        <div className="flex justify-center py-10">
          <HedgehogLoader className="h-10 w-auto" />
        </div>
      ) : summary ? (
        <>
          {/* 汇总：按单位 + 按日趋势 */}
          <div className="grid gap-3 md:grid-cols-2">
            <ChartCard title="按单位计量（总量）" aside={`口径：${summary.customer_id}`}>
              <HBars
                mode="single"
                data={summary.by_unit.map((u) => ({
                  label: u.unit,
                  value: Number(u.total),
                }))}
              />
            </ChartCard>
            <ChartCard
              title="按日事件数（近 14 天）"
              aside={
                summary.anomalies.length > 0
                  ? `峰值异常 ${summary.anomalies.length} 天`
                  : undefined
              }
            >
              <VBars
                data={[...summary.by_date]
                  .reverse()
                  .slice(0, 14)
                  .map((d) => ({ label: d.day.slice(5), value: d.n }))}
                unit=" 条"
              />
            </ChartCard>
          </div>

          {/* 汇总说明 + 峰值异常口径 */}
          <KV
            items={[
              { label: "未归属事件", value: summary.unattributed },
              { label: "账本口径", value: summary.note },
              ...(summary.anomalies.length > 0
                ? [
                    {
                      label: "峰值异常",
                      value: (
                        <span className="inline-flex flex-wrap items-center gap-1">
                          <StatusBadge kind="warn">
                            {summary.anomalies[0].rule}
                          </StatusBadge>
                          <span className="text-text-secondary">
                            {summary.anomalies
                              .map((a) => `${a.day}（${a.count} vs 均值 ${a.avg}）`)
                              .join("、")}
                          </span>
                        </span>
                      ),
                    },
                  ]
                : []),
            ]}
          />

          {/* 项目预算 */}
          <section className="space-y-2">
            <h3 className="font-display text-sm font-bold text-text-primary">
              项目预算
            </h3>
            <ApiTable
              rows={budgets}
              rowKey={(b) => b.project_id}
              cols={[
                { key: "name", label: "项目" },
                {
                  key: "budget_total",
                  label: "预算",
                  align: "right",
                  render: (b) =>
                    b.budget_total != null ? b.budget_total.toLocaleString("zh-CN") : "—",
                },
                {
                  key: "usage_events",
                  label: "事件数",
                  align: "right",
                  render: (b) => b.usage_events.toLocaleString("zh-CN"),
                },
                {
                  key: "note",
                  label: "口径",
                  render: (b) => (
                    <span className="text-xs text-text-secondary">{b.note}</span>
                  ),
                },
              ]}
              emptyText="无项目预算"
            />
          </section>

          {/* 明细 */}
          <section className="space-y-2">
            <h3 className="font-display text-sm font-bold text-text-primary">
              计量明细（最近 50 条）
            </h3>
            <ApiTable
              rows={rows}
              rowKey={(r) => r.usage_id}
              cols={[
                {
                  key: "occurred_at",
                  label: "时间",
                  render: (r) => (
                    <span className="text-text-secondary tabular-nums">
                      {shortTime(r.occurred_at)}
                    </span>
                  ),
                },
                { key: "unit", label: "单位" },
                {
                  key: "quantity",
                  label: "数量",
                  align: "right",
                  render: (r) => Number(r.quantity).toLocaleString("zh-CN"),
                },
                {
                  key: "run_id",
                  label: "run",
                  render: (r) =>
                    r.run_id ? (
                      <span className="text-text-secondary">
                        {r.run_id.slice(0, 12)}…（{r.run_status ?? "?"}）
                      </span>
                    ) : (
                      <span className="text-text-secondary">—</span>
                    ),
                },
                {
                  key: "profile_id",
                  label: "profile",
                  render: (r) => (
                    <span className="text-text-secondary">{r.profile_id || "—"}</span>
                  ),
                },
                {
                  key: "lineage",
                  label: "血缘",
                  render: (r) =>
                    r.lineage === "legacy_unattributed" ? (
                      <StatusBadge kind="warn">历史未归属</StatusBadge>
                    ) : (
                      <span className="text-xs text-text-secondary">
                        {r.source_evidence || r.evidence_bundle_id || "—"}
                      </span>
                    ),
                },
              ]}
              emptyText="无计量明细"
            />
          </section>

          {/* 历史未归属账本 + 追加式对账 */}
          <section className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-display text-sm font-bold text-text-primary">
                历史未归属账本
              </h3>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void reconcile()}
                disabled={reconBusy}
              >
                执行追加式对账
              </Button>
            </div>
            <p className="text-xs text-text-secondary">
              历史 Agent 调用无统一 BusinessRun；不篡改不可变 Usage、不猜测客户 /
              项目，只追加归属记录并诚实展示（幂等 append-only）。
            </p>
            {reconMsg && (
              <p className="text-xs text-text-secondary">{reconMsg}</p>
            )}
            <ApiTable
              rows={legacy}
              rowKey={(a) => a.attribution_id}
              cols={[
                {
                  key: "usage_id",
                  label: "usage",
                  render: (a) => (
                    <span className="text-text-secondary">
                      {a.usage_id.slice(0, 16)}…
                    </span>
                  ),
                },
                {
                  key: "attribution_status",
                  label: "状态",
                  render: (a) => <StatusBadge kind="warn">{a.attribution_status}</StatusBadge>,
                },
                {
                  key: "note",
                  label: "备注",
                  render: (a) => (
                    <span className="text-xs text-text-secondary">
                      {a.note.slice(0, 60)}
                    </span>
                  ),
                },
                {
                  key: "created_at",
                  label: "时间",
                  render: (a) => (
                    <span className="text-text-secondary tabular-nums">
                      {shortTime(a.created_at)}
                    </span>
                  ),
                },
              ]}
              emptyText="暂无历史未归属记录"
            />
          </section>
        </>
      ) : null}
    </div>
  );
}
