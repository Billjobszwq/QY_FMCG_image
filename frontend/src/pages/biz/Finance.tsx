/**
 * 财务与结算（P8）：合同与价目卡 / 账单与结算 两页签。
 *
 * 数据源（同源 /api/v1/finance/*，与 web/src/pages/Finance.tsx 一致；
 * Usage 台账部分来自 web/src/pages/UsageWorkbench.tsx 的 /api/v1/usage/*）：
 * —— GET  finance/contracts?customer_id=        合同列表
 * —— POST finance/contracts                     新建合同（usage + rc_standard）
 * —— GET  finance/rate-cards/rc_standard        价目卡（版本化）
 * —— GET  finance/invoices?customer_id=         账单列表
 * —— POST finance/invoices/generate             仅从 immutable Usage 生成草稿
 * —— GET  finance/invoices/{id}                 行级明细（下钻 usage/run/node/证据）
 * —— POST finance/invoices/{id}/issue | settle  开票 / 结算
 * —— POST finance/invoices/{id}/adjust          调整（append-only，原因必填）
 * —— GET  usage/summary | usage/legacy          不可变 Usage 账本（账单数据源）
 * —— POST usage/reconcile-legacy                追加式对账（不篡改 Usage）
 * —— GET  usage/export.csv                      CSV 导出（浏览器直接下载）
 */
import { useEffect, useState } from "react";
import { ApiError, fetchIamGet, fetchIamPost } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  ApiTable,
  errorMessageOf,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { HedgehogLoader } from "@/components/ui/loader";
import { HedgehogMascot } from "@/components/ui/mascot";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   类型
   ========================================================================== */

interface CustomerOption {
  customer_id: string;
  name: string;
}

interface FinanceContract {
  contract_id: string;
  kind: string;
  rate_card_id: string;
  status: string;
}

interface RateLine {
  unit: string;
  price: number;
}

interface RateCardBody {
  rate_card: { version: number; lines: RateLine[] };
}

interface InvoiceRow {
  invoice_id: string;
  period: string;
  status: string;
  total: number;
  net_total: number;
  rate_card_version: number;
}

interface DrilldownItem {
  run_id?: string;
  node?: string;
  source_evidence?: string;
  period?: string;
}

interface InvoiceLine {
  line_id: string;
  unit: string;
  quantity: number;
  unit_price: number;
  amount: number;
  drilldown?: DrilldownItem[];
}

interface InvoiceDetail {
  invoice_id: string;
  lines: InvoiceLine[];
  adjustments: { kind: string; amount: number; reason: string }[];
}

interface UsageByUnit {
  unit: string;
  total: number;
  n: number;
}

interface UsageSummaryBody {
  by_unit: UsageByUnit[];
  unattributed: number;
  note?: string;
}

interface LegacyAttribution {
  attribution_id: string;
  usage_id: string;
  attribution_status: string;
  note?: string;
  created_at: string;
}

/* ============================================================================
   本地小件：加载钩子 / 401 / 页签 / 状态映射 / 运营客户
   ========================================================================== */

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: unknown;
}

function useApi<T>(
  fetcher: (() => Promise<T>) | null,
  deps: readonly unknown[] = [],
): ApiState<T> & { reload: () => void } {
  const [st, setSt] = useState<ApiState<T>>({
    data: null,
    loading: fetcher !== null,
    error: null,
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!fetcher) {
      setSt({ data: null, loading: false, error: null });
      return;
    }
    let alive = true;
    setSt((s) => ({ data: s.data, loading: true, error: null }));
    fetcher().then(
      (d) => {
        if (alive) setSt({ data: d, loading: false, error: null });
      },
      (e: unknown) => {
        if (alive) setSt((s) => ({ data: s.data, loading: false, error: e }));
      },
    );
    return () => {
      alive = false;
    };
    // 依赖由调用方显式给出（客户 ID 等），闭包不参与比较
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);
  return { ...st, reload: () => setTick((t) => t + 1) };
}

function isNeedLogin(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

function useOpenLogin(): () => void {
  const openWindow = useWindowManager((s) => s.openWindow);
  return () =>
    openWindow({
      id: "login",
      title: "平台登录",
      content: <LoginWindow />,
      defaultPosition: {
        x: Math.max(24, Math.round(window.innerWidth / 2 - 190)),
        y: Math.max(24, Math.round(window.innerHeight / 2 - 210)),
      },
      defaultSize: { width: 380, height: 420 },
      minWidth: 320,
      minHeight: 380,
    });
}

function TabBar<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="tablist" className="flex items-center gap-1 border-b border-border">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={value === t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "-mb-px cursor-pointer border-b-2 px-3 py-1.5 text-[13px]",
            "transition-colors duration-200 ease-out",
            value === t.key
              ? "border-accent font-medium text-accent"
              : "border-transparent text-text-secondary hover:text-accent",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function statusKindOf(status: string): StatusKind {
  switch (status) {
    case "active":
    case "settled":
    case "issued":
      return "good";
    case "failed":
    case "cancelled":
    case "void":
      return "serious";
    case "overdue":
    case "blocked":
      return "warn";
    default:
      return "neutral";
  }
}

/** 运营客户上下文（SI4）：真实客户，单个自动预选，无客户诚实空态。 */
function useOperationalCustomer() {
  const st = useApi<{ customers?: CustomerOption[] }>(
    () => fetchIamGet("master/customers"),
    [],
  );
  const [customer, setCustomer] = useState("");
  const options = st.data?.customers ?? [];
  useEffect(() => {
    if (!customer && options.length === 1) setCustomer(options[0].customer_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customer, st.data]);
  return { customer, setCustomer, options };
}

function CustomerPicker({
  customer,
  setCustomer,
  options,
}: {
  customer: string;
  setCustomer: (c: string) => void;
  options: CustomerOption[];
}) {
  if (options.length === 0) {
    return (
      <p className="text-xs text-text-secondary">
        暂无运营客户 · 请先在“客户主数据”创建或经“导入中心”导入
      </p>
    );
  }
  return (
    <Select
      value={customer}
      aria-label="客户"
      className="w-64"
      onChange={(e) => setCustomer(e.target.value)}
    >
      {options.length > 1 && <option value="">请选择客户</option>}
      {options.map((c) => (
        <option key={c.customer_id} value={c.customer_id}>
          {c.name}（{c.customer_id}）
        </option>
      ))}
    </Select>
  );
}

function PickCustomerFirst() {
  return (
    <p className="rounded-md border border-border bg-background p-3 text-xs text-text-secondary">
      请先选择客户
    </p>
  );
}

/* ============================================================================
   页签一：合同与价目卡
   ========================================================================== */

function ContractsTab({ openLogin }: { openLogin: () => void }) {
  const { customer, setCustomer, options } = useOperationalCustomer();
  const contracts = useApi<{ contracts?: FinanceContract[] }>(
    customer
      ? () => fetchIamGet(`finance/contracts?customer_id=${customer}`)
      : null,
    [customer],
  );
  const rc = useApi<RateCardBody>(
    () => fetchIamGet("finance/rate-cards/rc_standard"),
    [],
  );
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isNeedLogin(contracts.error) || isNeedLogin(rc.error)) {
    return <NeedLoginState onOpenLogin={openLogin} />;
  }

  const contractCols: ApiTableCol<FinanceContract>[] = [
    { key: "contract_id", label: "contract_id" },
    { key: "kind", label: "类型" },
    { key: "rate_card_id", label: "价目卡" },
    {
      key: "status",
      label: "状态",
      render: (c) => (
        <StatusBadge kind={statusKindOf(c.status)}>{c.status}</StatusBadge>
      ),
    },
  ];

  const rateCols: ApiTableCol<RateLine>[] = [
    { key: "unit", label: "单位" },
    { key: "price", label: "单价", align: "right" },
  ];

  return (
    <div className="space-y-3">
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <div className="flex flex-wrap items-center gap-2">
          <CustomerPicker customer={customer} setCustomer={setCustomer} options={options} />
          {customer && (
            <Button
              size="sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setMsg(null);
                try {
                  await fetchIamPost("finance/contracts", {
                    customer_id: customer,
                    kind: "usage",
                    rate_card_id: "rc_standard",
                  });
                  setMsg("合同已创建");
                  contracts.reload();
                } catch (e) {
                  setMsg(`新建合同失败：${errorMessageOf(e)}`);
                } finally {
                  setBusy(false);
                }
              }}
            >
              新建合同（usage · rc_standard）
            </Button>
          )}
          {msg && <p className="text-xs text-text-secondary">{msg}</p>}
        </div>
      </section>

      {/* 价目卡（版本化；新版本只影响其后生成的账单） */}
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-[13px] font-semibold text-text-primary">
            价目卡 rc_standard
          </h3>
          {rc.data && (
            <span className="text-xs text-text-secondary">
              v{rc.data.rate_card.version}
            </span>
          )}
        </div>
        <ApiTable
          rows={rc.data?.rate_card.lines ?? []}
          cols={rateCols}
          loading={rc.loading}
          error={rc.error}
          onRetry={rc.reload}
          emptyText="价目卡暂无行"
          rowKey={(l) => l.unit}
        />
        <p className="text-[11px] text-text-secondary">
          rate card 版本化：价格变更仅限平台角色；新版本价目只影响其后生成的账单，
          已开票金额绑定开票时版本，历史账单不重算
        </p>
      </section>

      {/* 合同列表 */}
      {!customer ? (
        <PickCustomerFirst />
      ) : (
        <ApiTable
          rows={contracts.data?.contracts ?? []}
          cols={contractCols}
          loading={contracts.loading}
          error={contracts.error}
          onRetry={contracts.reload}
          emptyText="该客户暂无合同"
          rowKey={(c) => c.contract_id}
        />
      )}
    </div>
  );
}

/* ============================================================================
   页签二：账单与结算（含 Usage 台账：账单数据源）
   ========================================================================== */

function InvoicesTab({ openLogin }: { openLogin: () => void }) {
  const { customer, setCustomer, options } = useOperationalCustomer();
  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const invs = useApi<{ invoices?: InvoiceRow[] }>(
    customer
      ? () => fetchIamGet(`finance/invoices?customer_id=${customer}`)
      : null,
    [customer],
  );
  const summary = useApi<UsageSummaryBody>(
    customer
      ? () =>
          fetchIamGet(`usage/summary?customer_id=${encodeURIComponent(customer)}`)
      : null,
    [customer],
  );
  const legacy = useApi<{ attributions?: LegacyAttribution[] }>(
    () => fetchIamGet("usage/legacy"),
    [],
  );
  const [detail, setDetail] = useState<InvoiceDetail | null>(null);
  const [adjustFor, setAdjustFor] = useState<string | null>(null);
  const [adjAmount, setAdjAmount] = useState("-5");
  const [adjReason, setAdjReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (
    isNeedLogin(invs.error) ||
    isNeedLogin(summary.error) ||
    isNeedLogin(legacy.error)
  ) {
    return <NeedLoginState onOpenLogin={openLogin} />;
  }

  const unitCols: ApiTableCol<UsageByUnit>[] = [
    { key: "unit", label: "单位" },
    {
      key: "total",
      label: "总量",
      align: "right",
      render: (u) => Number(u.total).toLocaleString(),
    },
    { key: "n", label: "事件数", align: "right" },
  ];

  const legacyCols: ApiTableCol<LegacyAttribution>[] = [
    {
      key: "usage_id",
      label: "usage",
      render: (a) => `${String(a.usage_id).slice(0, 16)}…`,
    },
    {
      key: "attribution_status",
      label: "状态",
      render: (a) => (
        <StatusBadge kind="warn">{a.attribution_status}</StatusBadge>
      ),
    },
    {
      key: "note",
      label: "备注",
      render: (a) => String(a.note ?? "").slice(0, 60),
    },
    {
      key: "created_at",
      label: "时间",
      render: (a) => String(a.created_at).slice(0, 16),
    },
  ];

  const lineCols: ApiTableCol<InvoiceLine>[] = [
    { key: "unit", label: "单位" },
    { key: "quantity", label: "数量", align: "right" },
    { key: "unit_price", label: "单价", align: "right" },
    { key: "amount", label: "金额", align: "right" },
    {
      key: "drilldown",
      label: "下钻（usage/run/node/证据）",
      render: (l) => {
        const dd = l.drilldown ?? [];
        return (
          <span className="text-xs text-text-secondary">
            {dd.slice(0, 3).map((d, i) => (
              <span key={i} className="block">
                {d.run_id
                  ? `run ${String(d.run_id).slice(0, 12)}… / node ${d.node ?? "—"} / ${d.source_evidence ?? "—"}`
                  : `订阅 ${d.period ?? "—"}`}
              </span>
            ))}
            {dd.length > 3 ? `… 共 ${dd.length} 条` : dd.length === 0 ? "—" : ""}
          </span>
        );
      },
    },
  ];

  return (
    <div className="space-y-3">
      {/* 生成账单 */}
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <div className="flex flex-wrap items-center gap-2">
          <CustomerPicker customer={customer} setCustomer={setCustomer} options={options} />
          {customer && (
            <>
              <Input
                placeholder="期间 YYYY-MM"
                aria-label="期间"
                className="w-36"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              />
              <Button
                size="sm"
                disabled={busy || !period}
                onClick={async () => {
                  setBusy(true);
                  setMsg(null);
                  try {
                    const out = (await fetchIamPost("finance/invoices/generate", {
                      customer_id: customer,
                      period,
                    })) as { invoice: { invoice_id: string; total: number } };
                    setMsg(
                      `账单草稿已生成：${out.invoice.invoice_id} · 总额 ${out.invoice.total}`,
                    );
                    invs.reload();
                  } catch (e) {
                    setMsg(`生成账单失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                生成账单（来自 Usage）
              </Button>
            </>
          )}
          {msg && <p className="text-xs text-text-secondary">{msg}</p>}
        </div>
        <p className="text-[11px] text-text-secondary">
          账单仅从 immutable Usage 生成；每行可下钻 usage/run/node/证据；调整
          append-only；已开票金额不随新价格变动
        </p>
      </section>

      {/* 账单列表 */}
      {!customer ? (
        <PickCustomerFirst />
      ) : invs.error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-md border border-border bg-background py-6"
        >
          <StatusBadge kind="serious">加载失败</StatusBadge>
          <p className="max-w-[360px] text-center text-xs text-text-secondary">
            {errorMessageOf(invs.error)}
          </p>
          <Button variant="secondary" size="sm" onClick={invs.reload}>
            重试
          </Button>
        </div>
      ) : (
        <>
          {invs.loading && !invs.data && (
            <div className="flex justify-center py-6">
              <HedgehogLoader className="h-8 w-auto" />
            </div>
          )}
          {(invs.data?.invoices ?? []).length === 0 && !invs.loading && (
            <div className="flex flex-col items-center gap-1.5 rounded-md border border-border bg-background py-6">
              <HedgehogMascot className="h-16 w-auto" />
              <p className="text-xs text-text-secondary">
                该客户暂无账单：先生成 Usage 再开账单
              </p>
            </div>
          )}
          {(invs.data?.invoices ?? []).map((inv) => (
            <section
              key={inv.invoice_id}
              className="space-y-2 rounded-md border border-border bg-background p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-[13px] font-semibold text-text-primary">
                  {inv.invoice_id}
                </h3>
                <StatusBadge kind={statusKindOf(inv.status)}>{inv.status}</StatusBadge>
                <span className="text-xs text-text-secondary">
                  {inv.period} · total {inv.total} · net {inv.net_total} · 价目 v
                  {inv.rate_card_version}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setMsg(null);
                    try {
                      const out = (await fetchIamGet(
                        `finance/invoices/${inv.invoice_id}`,
                      )) as { invoice: InvoiceDetail };
                      setDetail(out.invoice);
                    } catch (e) {
                      setMsg(`详情失败：${errorMessageOf(e)}`);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  下钻明细
                </Button>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setMsg(null);
                    try {
                      await fetchIamPost(
                        `finance/invoices/${inv.invoice_id}/issue`,
                        {},
                      );
                      setMsg("已开票");
                      invs.reload();
                    } catch (e) {
                      setMsg(`开票失败：${errorMessageOf(e)}`);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  开票
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() => {
                    setAdjustFor(adjustFor === inv.invoice_id ? null : inv.invoice_id);
                    setAdjReason("");
                    setAdjAmount("-5");
                  }}
                >
                  调整
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setMsg(null);
                    try {
                      await fetchIamPost(
                        `finance/invoices/${inv.invoice_id}/settle`,
                        {},
                      );
                      setMsg("已结算");
                      invs.reload();
                    } catch (e) {
                      setMsg(`结算失败：${errorMessageOf(e)}`);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  结算
                </Button>
              </div>
              {adjustFor === inv.invoice_id && (
                <div className="flex flex-wrap items-center gap-2 rounded-md border border-dashed border-border-strong p-2.5">
                  <Input
                    type="number"
                    aria-label="调整金额"
                    className="w-28"
                    value={adjAmount}
                    onChange={(e) => setAdjAmount(e.target.value)}
                  />
                  <Input
                    placeholder="调整原因（必填，append-only 留痕）"
                    aria-label="调整原因"
                    className="min-w-56 flex-1"
                    value={adjReason}
                    onChange={(e) => setAdjReason(e.target.value)}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy || !adjReason.trim()}
                    onClick={async () => {
                      setBusy(true);
                      setMsg(null);
                      try {
                        await fetchIamPost(
                          `finance/invoices/${inv.invoice_id}/adjust`,
                          {
                            kind: "discount",
                            amount: Number(adjAmount),
                            reason: adjReason.trim(),
                          },
                        );
                        setMsg("调整已追加（append-only）");
                        setAdjustFor(null);
                        invs.reload();
                        if (detail?.invoice_id === inv.invoice_id) setDetail(null);
                      } catch (e) {
                        setMsg(`调整失败：${errorMessageOf(e)}`);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    追加调整
                  </Button>
                </div>
              )}
              {detail && detail.invoice_id === inv.invoice_id && (
                <div className="space-y-2">
                  <ApiTable
                    rows={detail.lines}
                    cols={lineCols}
                    emptyText="账单无明细行"
                    rowKey={(l) => l.line_id}
                  />
                  {(detail.adjustments ?? []).length > 0 && (
                    <p className="text-[11px] text-text-secondary">
                      调整：
                      {(detail.adjustments ?? [])
                        .map((a) => `${a.kind} ${a.amount}（${a.reason}）`)
                        .join("；")}
                    </p>
                  )}
                </div>
              )}
            </section>
          ))}
        </>
      )}

      {/* Usage 台账：账单数据源（web UsageWorkbench 的瘦版） */}
      {customer && (
        <section className="space-y-2 rounded-md border border-border bg-background p-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[13px] font-semibold text-text-primary">
              Usage 台账（账单数据源）
            </h3>
            <span className="text-[11px] text-text-secondary">
              不可变账本 · 同源 /api/v1/usage/*
            </span>
            <span className="ml-auto">
              <Button variant="secondary" size="sm" asChild>
                <a
                  href={`/api/v1/usage/export.csv?customer_id=${encodeURIComponent(customer)}`}
                >
                  导出 CSV
                </a>
              </Button>
            </span>
          </div>
          <ApiTable
            rows={summary.data?.by_unit ?? []}
            cols={unitCols}
            loading={summary.loading}
            error={summary.error}
            onRetry={summary.reload}
            emptyText="该客户暂无 Usage"
            rowKey={(u) => u.unit}
          />
          {summary.data && (
            <KV
              items={[
                { label: "未归属事件", value: summary.data.unattributed },
                ...(summary.data.note ? [{ label: "口径", value: summary.data.note }] : []),
              ]}
            />
          )}
          <div className="space-y-1.5 pt-1">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-xs font-semibold text-text-primary">
                历史未归属账本（追加式对账）
              </h4>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setMsg(null);
                  try {
                    const out = (await fetchIamPost("usage/reconcile-legacy", {})) as {
                      added: number;
                      legacy_total: number;
                    };
                    setMsg(
                      `已追加 ${out.added} 条归属记录（累计 ${out.legacy_total}）`,
                    );
                    legacy.reload();
                  } catch (e) {
                    setMsg(`对账失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                执行追加式对账
              </Button>
            </div>
            <p className="text-[11px] text-text-secondary">
              历史 Agent 调用无统一 BusinessRun；不篡改不可变
              Usage、不猜测客户/项目，只追加归属记录并诚实展示
            </p>
            <ApiTable
              rows={legacy.data?.attributions ?? []}
              cols={legacyCols}
              loading={legacy.loading}
              error={legacy.error}
              onRetry={legacy.reload}
              emptyText="暂无历史未归属记录"
              rowKey={(a) => a.attribution_id}
            />
          </div>
        </section>
      )}
    </div>
  );
}

/* ============================================================================
   页面入口
   ========================================================================== */

type FinanceTab = "contracts" | "invoices";

export default function FinancePage() {
  const [tab, setTab] = useState<FinanceTab>("contracts");
  const openLogin = useOpenLogin();
  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="财务与结算"
        desc="合同与价目卡（rate card 版本化）→ 账单仅从 immutable Usage 生成（行可下钻证据，调整 append-only）"
      />
      <TabBar<FinanceTab>
        tabs={[
          { key: "contracts", label: "合同与价目卡" },
          { key: "invoices", label: "账单与结算" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "contracts" && <ContractsTab openLogin={openLogin} />}
      {tab === "invoices" && <InvoicesTab openLogin={openLogin} />}
    </div>
  );
}
