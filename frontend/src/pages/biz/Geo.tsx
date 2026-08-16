/**
 * 位置与外勤（P8）：地址与地理编码 / 任务与路线 / 围栏与到店 三页签。
 *
 * 数据源（同源 /api/v1/geo/*，与 web/src/pages/Geo.tsx 一致）：
 * —— GET  geo/providers                        地理编码/地图/路线求解能力
 * —— GET  geo/addresses?customer_id=           地址候选（含置信度）
 * —— POST geo/addresses                        入库待地理编码
 * —— POST geo/addresses/{id}/verify            人工确认候选坐标（低置信必须）
 * —— POST geo/addresses/{id}/geocode           Provider 取坐标（可降级）
 * —— POST geo/addresses/{id}/manual-coords     手工/导入坐标
 * —— GET  geo/tasks | geo/plans | geo/employees | geo/fences
 * —— POST geo/tasks                            建外勤任务（门头必拍）
 * —— POST geo/plans                            VRP 规划（多项目硬隔离）
 * —— POST geo/tasks/{id}/dispatch | arrive | evidence | complete
 * —— POST geo/fences                           建围栏
 *
 * 瘦版说明：不引入 maplibre 等重库，地图瓦片不渲染；
 * geo/providers 的能力状态如实展示（缺失即诚实标注）。
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

interface GeoCandidate {
  lat: number;
  lng: number;
  confidence: number;
}

interface GeoAddress {
  address_id: string;
  raw: string;
  status: string;
  confidence: number;
  candidates: GeoCandidate[];
  chosen?: { lat: number; lng: number; source?: string } | null;
  verified_by?: string;
}

interface GeoTask {
  task_id: string;
  status: string;
  require_storefront?: boolean;
  selfie_required?: boolean;
  assignee?: string;
}

interface GeoStop {
  seq: number;
  task_id: string;
  lat: number;
  lng: number;
  leg_km: number;
}

interface GeoPlan {
  plan_id: string;
  status: string;
  stops: GeoStop[];
  unassigned: { task_id: string; reason: string }[];
  cost: { total: number; total_km: number };
}

interface GeoFence {
  fence_id: string;
  name: string;
  lat: number;
  lng: number;
  radius_m: number;
}

interface GeoEmployee {
  employee_id: string;
  name: string;
}

interface GeoProviders {
  geocoder: { available: boolean; reason?: string };
  map: { available: boolean; tiles_url?: string; reason?: string };
  solver?: { name?: string };
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
    case "verified":
    case "completed":
    case "done":
      return "good";
    case "failed":
    case "rejected":
    case "cancelled":
      return "serious";
    case "pending":
    case "degraded":
    case "blocked":
      return "warn";
    default:
      return "neutral";
  }
}

/**
 * 运营客户上下文（SI4）：只从 master/customers 真实客户中选择，
 * 有且仅有一个时自动预选；无客户时诚实空态，不回退测试客户。
 */
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
  return {
    customer,
    setCustomer,
    options,
    customersLoading: st.loading,
    customersError: st.error,
    reloadCustomers: st.reload,
  };
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

/** 未选客户时的占位提示（诚实空态）。 */
function PickCustomerFirst() {
  return (
    <p className="rounded-md border border-border bg-background p-3 text-xs text-text-secondary">
      请先选择客户
    </p>
  );
}

/** 接口错误块（非 401）：serious 徽章 + 重试。 */
function ErrorBlock({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 rounded-md border border-border bg-background py-6"
    >
      <StatusBadge kind="serious">加载失败</StatusBadge>
      <p className="max-w-[360px] text-center text-xs text-text-secondary">
        {message}
      </p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

/* ============================================================================
   页签一：地址与地理编码
   ========================================================================== */

function AddressesTab({ openLogin }: { openLogin: () => void }) {
  const { customer, setCustomer, options } = useOperationalCustomer();
  const providers = useApi<GeoProviders>(() => fetchIamGet("geo/providers"), []);
  const addrs = useApi<{ addresses?: GeoAddress[] }>(
    customer ? () => fetchIamGet(`geo/addresses?customer_id=${customer}`) : null,
    [customer],
  );
  const [raw, setRaw] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(true);
    setMsg(null);
    try {
      const out = await fn();
      setMsg(`${label}成功`);
      addrs.reload();
      return out;
    } catch (e) {
      setMsg(`${label}失败：${errorMessageOf(e)}`);
      return null;
    } finally {
      setBusy(false);
    }
  }

  if (isNeedLogin(addrs.error) || isNeedLogin(providers.error)) {
    return <NeedLoginState onOpenLogin={openLogin} />;
  }

  const mp = providers.data;
  const candCols: ApiTableCol<GeoCandidate & { address: GeoAddress; index: number }>[] = [
    { key: "idx", label: "候选", render: (c) => `候选${c.index + 1}` },
    {
      key: "coords",
      label: "坐标",
      render: (c) => (
        <span className="tabular-nums">
          ({c.lat}, {c.lng})
        </span>
      ),
    },
    {
      key: "confidence",
      label: "conf",
      align: "right",
      render: (c) => c.confidence,
    },
    {
      key: "op",
      label: "操作",
      render: (c) =>
        c.address.status === "pending" ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() =>
              act("人工确认经纬度", () =>
                fetchIamPost(`geo/addresses/${c.address.address_id}/verify`, {
                  chosen_index: c.index,
                }),
              )
            }
          >
            确认此候选
          </Button>
        ) : (
          <span className="text-xs text-text-secondary">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-3">
      {/* Provider 能力（地图缺失诚实回退） */}
      <section className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md border border-border bg-background p-3 text-xs text-text-secondary">
        <span>地理编码</span>
        {mp ? (
          <StatusBadge kind={mp.geocoder.available ? "good" : "warn"}>
            {mp.geocoder.available ? "可用" : (mp.geocoder.reason ?? "不可用")}
          </StatusBadge>
        ) : (
          <span>—</span>
        )}
        <span>地图</span>
        {mp ? (
          <StatusBadge kind={mp.map.available ? "good" : "warn"}>
            {mp.map.available
              ? `可用（${mp.map.tiles_url ?? "默认瓦片"}）`
              : (mp.map.reason ?? "不可用")}
          </StatusBadge>
        ) : (
          <span>—</span>
        )}
        <span>路线求解</span>
        <span className="text-text-primary">{mp?.solver?.name ?? "—"}</span>
        <span className="ml-auto">
          瘦版不集成地图瓦片（不引入 maplibre），坐标以列表呈现
        </span>
      </section>

      {/* 客户与入库 */}
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <CustomerPicker customer={customer} setCustomer={setCustomer} options={options} />
        {customer && (
          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="原始地址（含 [geo] 标记=高置信样例）"
              aria-label="原始地址"
              className="min-w-64 flex-1"
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
            />
            <Button
              size="sm"
              disabled={busy || !raw}
              onClick={async () => {
                setBusy(true);
                setMsg(null);
                try {
                  await fetchIamPost("geo/addresses", {
                    customer_id: customer,
                    raw,
                  });
                  setMsg("地址已入库（候选待确认）");
                  setRaw("");
                  addrs.reload();
                } catch (e) {
                  setMsg(`地理编码失败：${errorMessageOf(e)}`);
                } finally {
                  setBusy(false);
                }
              }}
            >
              地理编码
            </Button>
          </div>
        )}
        {msg && <p className="text-xs text-text-secondary">{msg}</p>}
      </section>

      {/* 地址列表 */}
      {!customer ? (
        <PickCustomerFirst />
      ) : addrs.error ? (
        <ErrorBlock message={errorMessageOf(addrs.error)} onRetry={addrs.reload} />
      ) : (
        (addrs.data?.addresses ?? []).map((a) => (
          <section
            key={a.address_id}
            className="space-y-2 rounded-md border border-border bg-background p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-text-primary">{a.raw}</h3>
              <StatusBadge kind={statusKindOf(a.status)}>{a.status}</StatusBadge>
              <span className="text-xs text-text-secondary">
                {a.address_id} · 置信度 {a.confidence}
              </span>
            </div>
            {a.candidates.length > 0 ? (
              <ApiTable
                rows={a.candidates.map((c, i) => ({
                  ...c,
                  address: a,
                  index: i,
                }))}
                cols={candCols}
                emptyText="无候选坐标"
                rowKey={(_, i) => `cand-${i}`}
              />
            ) : (
              <p className="text-xs text-text-secondary">暂无候选坐标</p>
            )}
            {a.status === "verified" && a.chosen && (
              <p className="text-xs text-text-secondary">
                已确认：
                <span className="tabular-nums">
                  ({a.chosen.lat}, {a.chosen.lng})
                </span>
                {" "}· 确认人 {a.verified_by ?? "—"}
                {a.chosen.source ? ` · 来源 ${a.chosen.source}` : ""}
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setMsg(null);
                  try {
                    const r = (await fetchIamPost(
                      `geo/addresses/${a.address_id}/geocode`,
                      {},
                    )) as { status: string; reason?: string };
                    setMsg(
                      r.status === "degraded"
                        ? `获取坐标降级：${r.reason ?? "provider 不可用"}`
                        : `获取坐标完成：${r.status}`,
                    );
                    addrs.reload();
                  } catch (e) {
                    setMsg(`获取坐标失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                获取坐标（Provider）
              </Button>
              <ManualCoordsForm
                addressId={a.address_id}
                disabled={busy}
                onDone={(m) => {
                  setMsg(m);
                  addrs.reload();
                }}
              />
            </div>
          </section>
        ))
      )}
      {customer &&
        !addrs.loading &&
        !addrs.error &&
        (addrs.data?.addresses ?? []).length === 0 && (
          <div className="flex flex-col items-center gap-1.5 rounded-md border border-border bg-background py-6">
            <HedgehogMascot className="h-16 w-auto" />
            <p className="text-xs text-text-secondary">该客户暂无地址</p>
          </div>
        )}
    </div>
  );
}

/** 手工/导入坐标（低置信兜底，source=manual 留痕）。 */
function ManualCoordsForm({
  addressId,
  disabled,
  onDone,
}: {
  addressId: string;
  disabled: boolean;
  onDone: (msg: string) => void;
}) {
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        手工/导入坐标
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <Input
        className="w-24"
        placeholder="纬度"
        aria-label="纬度"
        value={lat}
        onChange={(e) => setLat(e.target.value)}
      />
      <Input
        className="w-24"
        placeholder="经度"
        aria-label="经度"
        value={lng}
        onChange={(e) => setLng(e.target.value)}
      />
      <Button
        variant="secondary"
        size="sm"
        disabled={disabled || !lat || !lng}
        onClick={async () => {
          try {
            await fetchIamPost(`geo/addresses/${addressId}/manual-coords`, {
              lat: Number(lat),
              lng: Number(lng),
              source: "manual",
            });
            onDone("手工坐标已确认（source=manual）");
          } catch (e) {
            onDone(`手工坐标失败：${errorMessageOf(e)}`);
          }
        }}
      >
        确认
      </Button>
    </span>
  );
}

/* ============================================================================
   页签二：任务与路线
   ========================================================================== */

function FieldTab({ openLogin }: { openLogin: () => void }) {
  const { customer, setCustomer, options } = useOperationalCustomer();
  const tasks = useApi<{ tasks?: GeoTask[] }>(
    customer ? () => fetchIamGet(`geo/tasks?customer_id=${customer}`) : null,
    [customer],
  );
  const plans = useApi<{ plans?: GeoPlan[] }>(
    customer ? () => fetchIamGet(`geo/plans?customer_id=${customer}`) : null,
    [customer],
  );
  const addrs = useApi<{ addresses?: GeoAddress[] }>(
    customer ? () => fetchIamGet(`geo/addresses?customer_id=${customer}`) : null,
    [customer],
  );
  const emps = useApi<{ employees?: GeoEmployee[] }>(
    customer ? () => fetchIamGet(`geo/employees?customer_id=${customer}`) : null,
    [customer],
  );
  const [form, setForm] = useState({ address_id: "", project_id: "", selfie: false });
  const [planSel, setPlanSel] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (
    isNeedLogin(tasks.error) ||
    isNeedLogin(plans.error) ||
    isNeedLogin(addrs.error)
  ) {
    return <NeedLoginState onOpenLogin={openLogin} />;
  }

  const taskCols: ApiTableCol<GeoTask>[] = [
    {
      key: "plan",
      label: "规划",
      render: (t) => (
        <input
          type="checkbox"
          aria-label={`勾选 ${t.task_id}`}
          checked={planSel.includes(t.task_id)}
          onChange={(e) =>
            setPlanSel((s) =>
              e.target.checked
                ? [...s, t.task_id]
                : s.filter((x) => x !== t.task_id),
            )
          }
        />
      ),
    },
    { key: "task_id", label: "任务", render: (t) => `${t.task_id.slice(0, 12)}…` },
    {
      key: "status",
      label: "状态",
      render: (t) => <StatusBadge kind={statusKindOf(t.status)}>{t.status}</StatusBadge>,
    },
    {
      key: "require_storefront",
      label: "门头必拍",
      render: (t) => (t.require_storefront ? "是" : "否"),
    },
    {
      key: "selfie_required",
      label: "自拍",
      render: (t) => (t.selfie_required ? "启用" : "关闭"),
    },
    { key: "assignee", label: "执行人" },
  ];

  return (
    <div className="space-y-3">
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <CustomerPicker customer={customer} setCustomer={setCustomer} options={options} />
        {customer && (
          <>
            <h3 className="text-[13px] font-semibold text-text-primary">
              新建外勤任务
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={form.address_id}
                aria-label="地址"
                className="w-72"
                onChange={(e) => setForm({ ...form, address_id: e.target.value })}
              >
                <option value="">选择地址…</option>
                {(addrs.data?.addresses ?? []).map((a) => (
                  <option key={a.address_id} value={a.address_id}>
                    {a.raw}（{a.status}）
                  </option>
                ))}
              </Select>
              <Input
                placeholder="project_id"
                aria-label="项目"
                className="w-40"
                value={form.project_id}
                onChange={(e) => setForm({ ...form, project_id: e.target.value })}
              />
              <label className="inline-flex items-center gap-1 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={form.selfie}
                  onChange={(e) => setForm({ ...form, selfie: e.target.checked })}
                />
                启用自拍（人脸比对默认不自动触发）
              </label>
              <Button
                size="sm"
                disabled={busy || !form.address_id}
                onClick={async () => {
                  setBusy(true);
                  setMsg(null);
                  try {
                    await fetchIamPost("geo/tasks", {
                      customer_id: customer,
                      address_id: form.address_id,
                      project_id: form.project_id,
                      require_storefront: true,
                      selfie_required: form.selfie,
                    });
                    setMsg("任务已创建");
                    tasks.reload();
                  } catch (e) {
                    setMsg(`建任务失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                建任务（门头必拍）
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button
                variant="secondary"
                size="sm"
                disabled={busy || planSel.length === 0}
                onClick={async () => {
                  setBusy(true);
                  setMsg(null);
                  try {
                    const out = (await fetchIamPost("geo/plans", {
                      customer_id: customer,
                      task_ids: planSel,
                      constraints: {},
                    })) as {
                      plan: { stops: unknown[]; unassigned: unknown[]; cost: { total: number } };
                    };
                    setMsg(
                      `路线已生成：${out.plan.stops.length} 站 · 未分配 ${out.plan.unassigned.length} · 成本 ${out.plan.cost.total} 元`,
                    );
                    plans.reload();
                  } catch (e) {
                    setMsg(`规划失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                规划路线（勾选 {planSel.length} 个任务）
              </Button>
              <span className="text-[11px] text-text-secondary">
                VRP 最近邻 + 约束（max_km/多项目硬隔离）；未分配原因显式留痕
              </span>
            </div>
          </>
        )}
        {msg && <p className="text-xs text-text-secondary">{msg}</p>}
      </section>

      {!customer ? (
        <PickCustomerFirst />
      ) : (
        <>
          <ApiTable
            rows={tasks.data?.tasks ?? []}
            cols={taskCols}
            loading={tasks.loading}
            error={tasks.error}
            onRetry={tasks.reload}
            emptyText="暂无外勤任务"
            rowKey={(t) => t.task_id}
          />
          {(plans.data?.plans ?? []).map((p) => (
            <section
              key={p.plan_id}
              className="space-y-2 rounded-md border border-border bg-background p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-[13px] font-semibold text-text-primary">
                  {p.plan_id}
                </h3>
                <StatusBadge kind={statusKindOf(p.status)}>{p.status}</StatusBadge>
                <span className="text-xs text-text-secondary">
                  {p.stops.length} 站 · {p.cost.total_km} km · {p.cost.total} 元
                </span>
              </div>
              {p.unassigned.length > 0 && (
                <ul className="space-y-1">
                  {p.unassigned.map((u, i) => (
                    <li key={i} className="flex items-center gap-1.5">
                      <StatusBadge kind="warn">未分配</StatusBadge>
                      <span className="text-xs text-text-secondary">
                        {u.task_id.slice(0, 10)}…：{u.reason}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <ApiTable
                rows={p.stops}
                cols={[
                  { key: "seq", label: "序", align: "right" },
                  {
                    key: "task_id",
                    label: "任务",
                    render: (s) => `${s.task_id.slice(0, 12)}…`,
                  },
                  {
                    key: "coords",
                    label: "坐标",
                    render: (s) => (
                      <span className="tabular-nums">
                        ({s.lat}, {s.lng})
                      </span>
                    ),
                  },
                  { key: "leg_km", label: "leg km", align: "right" },
                  {
                    key: "op",
                    label: "派发",
                    render: (s) => (
                      <DispatchCell
                        taskId={s.task_id}
                        planId={p.plan_id}
                        employees={emps.data?.employees ?? []}
                        onMsg={(m) => {
                          setMsg(m);
                          tasks.reload();
                        }}
                      />
                    ),
                  },
                ]}
                emptyText="无站点"
                rowKey={(s) => `${p.plan_id}-${s.seq}`}
              />
            </section>
          ))}
        </>
      )}
    </div>
  );
}

/** 站点派发：选员工 → POST geo/tasks/{id}/dispatch。 */
function DispatchCell({
  taskId,
  planId,
  employees,
  onMsg,
}: {
  taskId: string;
  planId: string;
  employees: GeoEmployee[];
  onMsg: (m: string) => void;
}) {
  const [emp, setEmp] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <span className="inline-flex items-center gap-1.5">
      <Select
        value={emp}
        aria-label="执行人"
        className="w-32"
        onChange={(e) => setEmp(e.target.value)}
      >
        <option value="">员工…</option>
        {employees.map((e) => (
          <option key={e.employee_id} value={e.employee_id}>
            {e.name}
          </option>
        ))}
      </Select>
      <Button
        variant="secondary"
        size="sm"
        disabled={!emp || busy}
        onClick={async () => {
          setBusy(true);
          try {
            await fetchIamPost(`geo/tasks/${taskId}/dispatch`, {
              employee_id: emp,
              plan_id: planId,
            });
            onMsg("已派发");
          } catch (e) {
            onMsg(`派发失败：${errorMessageOf(e)}`);
          } finally {
            setBusy(false);
          }
        }}
      >
        派发
      </Button>
    </span>
  );
}

/* ============================================================================
   页签三：围栏与到店
   ========================================================================== */

function VisitTab({ openLogin }: { openLogin: () => void }) {
  const { customer, setCustomer, options } = useOperationalCustomer();
  const fences = useApi<{ fences?: GeoFence[] }>(
    customer ? () => fetchIamGet(`geo/fences?customer_id=${customer}`) : null,
    [customer],
  );
  const tasks = useApi<{ tasks?: GeoTask[] }>(
    customer ? () => fetchIamGet(`geo/tasks?customer_id=${customer}`) : null,
    [customer],
  );
  const [form, setForm] = useState({ name: "", lat: "31.0", lng: "121.0", radius: "150" });
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isNeedLogin(fences.error) || isNeedLogin(tasks.error)) {
    return <NeedLoginState onOpenLogin={openLogin} />;
  }

  const fenceCols: ApiTableCol<GeoFence>[] = [
    {
      key: "name",
      label: "名称",
      render: (f) => (
        <span>
          {f.name}{" "}
          <span className="text-xs text-text-secondary">{f.fence_id}</span>
        </span>
      ),
    },
    {
      key: "center",
      label: "中心坐标",
      render: (f) => (
        <span className="tabular-nums">
          ({f.lat}, {f.lng})
        </span>
      ),
    },
    { key: "radius_m", label: "半径(m)", align: "right" },
  ];

  return (
    <div className="space-y-3">
      <section className="space-y-2 rounded-md border border-border bg-background p-3">
        <CustomerPicker customer={customer} setCustomer={setCustomer} options={options} />
        {customer && (
          <>
            <h3 className="text-[13px] font-semibold text-text-primary">新建围栏</h3>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                placeholder="名称"
                aria-label="围栏名称"
                className="w-40"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
              <Input
                className="w-28"
                aria-label="纬度"
                value={form.lat}
                onChange={(e) => setForm({ ...form, lat: e.target.value })}
              />
              <Input
                className="w-28"
                aria-label="经度"
                value={form.lng}
                onChange={(e) => setForm({ ...form, lng: e.target.value })}
              />
              <Input
                className="w-28"
                aria-label="半径(米)"
                value={form.radius}
                onChange={(e) => setForm({ ...form, radius: e.target.value })}
              />
              <Button
                size="sm"
                disabled={busy || !form.name}
                onClick={async () => {
                  setBusy(true);
                  setMsg(null);
                  try {
                    await fetchIamPost("geo/fences", {
                      customer_id: customer,
                      name: form.name,
                      lat: Number(form.lat),
                      lng: Number(form.lng),
                      radius_m: Number(form.radius),
                    });
                    setMsg("围栏已创建");
                    fences.reload();
                  } catch (e) {
                    setMsg(`创建围栏失败：${errorMessageOf(e)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                创建
              </Button>
            </div>
          </>
        )}
        {msg && <p className="text-xs text-text-secondary">{msg}</p>}
      </section>

      {!customer ? (
        <PickCustomerFirst />
      ) : (
        <>
          <ApiTable
            rows={fences.data?.fences ?? []}
            cols={fenceCols}
            loading={fences.loading}
            error={fences.error}
            onRetry={fences.reload}
            emptyText="暂无围栏"
            rowKey={(f) => f.fence_id}
          />
          <section className="space-y-2 rounded-md border border-border bg-background p-3">
            <h3 className="text-[13px] font-semibold text-text-primary">
              任务到店 / 证据 / 完成
            </h3>
            <p className="text-[11px] text-text-secondary">
              围栏 enter 事件（半径+精度校验）；门头必拍；差旅费随完成生成
            </p>
            {tasks.loading && (
              <div className="flex justify-center py-4">
                <HedgehogLoader className="h-8 w-auto" />
              </div>
            )}
            {(tasks.data?.tasks ?? []).map((t) => (
              <VisitRow
                key={t.task_id}
                t={t}
                fences={fences.data?.fences ?? []}
                onMsg={(m) => {
                  setMsg(m);
                  tasks.reload();
                }}
              />
            ))}
            {!tasks.loading && (tasks.data?.tasks ?? []).length === 0 && (
              <div className="flex flex-col items-center gap-1.5 py-4">
                <HedgehogMascot className="h-16 w-auto" />
                <p className="text-xs text-text-secondary">
                  暂无任务：先到“任务与路线”派发
                </p>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

/** 单任务到店流转：dispatched → arrive；arrived → evidence/complete。 */
function VisitRow({
  t,
  fences,
  onMsg,
}: {
  t: GeoTask;
  fences: GeoFence[];
  onMsg: (m: string) => void;
}) {
  const [fence, setFence] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-1.5 rounded-md border border-dashed border-border-strong p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-text-primary">
          {t.task_id.slice(0, 12)}…
        </span>
        <StatusBadge kind={statusKindOf(t.status)}>{t.status}</StatusBadge>
        <span className="text-xs text-text-secondary">
          门头必拍：{t.require_storefront ? "是" : "否"} · 自拍：
          {t.selfie_required ? "启用" : "关闭（人脸不自动触发）"}
        </span>
      </div>
      {t.status === "dispatched" && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Select
            value={fence}
            aria-label="围栏"
            className="w-44"
            onChange={(e) => setFence(e.target.value)}
          >
            <option value="">围栏…</option>
            {fences.map((f) => (
              <option key={f.fence_id} value={f.fence_id}>
                {f.name}
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            size="sm"
            disabled={!fence || busy}
            onClick={async () => {
              const f = fences.find((x) => x.fence_id === fence);
              if (!f) return;
              setBusy(true);
              try {
                await fetchIamPost(`geo/tasks/${t.task_id}/arrive`, {
                  fence_id: fence,
                  lat: f.lat,
                  lng: f.lng,
                  accuracy: 8,
                  employee_id: t.assignee,
                });
                onMsg("已到店（围栏 enter 事件已记录）");
              } catch (e) {
                onMsg(`到店失败：${errorMessageOf(e)}`);
              } finally {
                setBusy(false);
              }
            }}
          >
            到店打卡
          </Button>
        </div>
      )}
      {t.status === "arrived" && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await fetchIamPost(`geo/tasks/${t.task_id}/evidence`, {
                  kind: "storefront",
                  media_ref: "cas:web-upload",
                  location: {},
                });
                onMsg("门头照片证据已入库");
              } catch (e) {
                onMsg(`证据失败：${errorMessageOf(e)}`);
              } finally {
                setBusy(false);
              }
            }}
          >
            上传门头照
          </Button>
          <Button
            size="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const out = (await fetchIamPost(
                  `geo/tasks/${t.task_id}/complete`,
                  {},
                )) as { travel_cost: { amount: number; km: number } };
                onMsg(
                  `已完成：差旅费 ${out.travel_cost.amount} 元（${out.travel_cost.km} km）`,
                );
              } catch (e) {
                onMsg(`完成失败：${errorMessageOf(e)}`);
              } finally {
                setBusy(false);
              }
            }}
          >
            完成（生成差旅费）
          </Button>
        </div>
      )}
    </div>
  );
}

/* ============================================================================
   页面入口
   ========================================================================== */

type GeoTab = "addresses" | "field" | "visit";

export default function GeoPage() {
  const [tab, setTab] = useState<GeoTab>("addresses");
  const openLogin = useOpenLogin();
  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="位置与外勤"
        desc="地址候选+置信度（低置信必须人工确认）→ VRP 路线（多项目硬隔离）→ 围栏到店与差旅费；人脸比对默认不自动触发"
      />
      <TabBar<GeoTab>
        tabs={[
          { key: "addresses", label: "地址与地理编码" },
          { key: "field", label: "任务与路线" },
          { key: "visit", label: "围栏与到店" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "addresses" && <AddressesTab openLogin={openLogin} />}
      {tab === "field" && <FieldTab openLogin={openLogin} />}
      {tab === "visit" && <VisitTab openLogin={openLogin} />}
    </div>
  );
}
