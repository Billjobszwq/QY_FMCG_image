/**
 * 客户主数据（/master/customers）—— v3 真实数据页面（P6）。
 *
 * 数据源（全部同源 /api/v1/*，无样本数据）：
 * —— GET  /master/customers?include_fixture=true   客户列表（含 fixture 标记）
 * —— GET  /master/duplicates                       合并建议（规范化重名，不自动合并）
 * —— POST master/customers                         新建客户（测试客户须绑定 test_run_id）
 * —— POST master/customer/{id}/status              停用 / 启用（可逆开关，与 web 一致直接可调）
 * —— GET  master/customers/{id}/overview           隔离概览（runs / 任务 / Usage）
 *
 * 状态纪律：401 → NeedLoginState；网络错误 → ErrorState+重试；
 * 加载 / 空态由 ApiTable 内置（HedgehogLoader / HedgehogMascot）。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, fetchIamGet, fetchIamPost } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { getWindowManager } from "@/store/windowStore";

/* ============================================================================
   契约类型（与 web IamMaster.tsx 实际消费字段一致）
   ========================================================================== */

interface CustomerRow {
  customer_id: string;
  name: string;
  status: string;
  retention_policy: string | null;
  is_test_fixture: boolean;
  test_run_id: string | null;
  data_scope?: string;
}

interface OverviewBody {
  customer_id: string;
  runs: number;
  tasks: number;
  work_items: number;
  events: number;
  usage: { unit: string; quantity: number }[];
  error?: string;
}

interface DupGroups {
  customers: { name_key: string; ids: string[] }[];
  skus: { name_key: string; ids: string[] }[];
}

interface ActionMsg {
  ok: boolean;
  text: string;
}

/* ============================================================================
   轻量数据 hook（与 P6 其余页面同构）
   ========================================================================== */

function useApi<T>(fetcher: (() => Promise<T>) | null, deps: readonly unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(fetcher !== null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!fetcher) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    fetcher().then(
      (d) => {
        if (!alive) return;
        setData(d);
        setLoading(false);
      },
      (e: unknown) => {
        if (!alive) return;
        setData(null);
        setError(e);
        setLoading(false);
      },
    );
    return () => {
      alive = false;
    };
    // fetcher 每次渲染重建，不入依赖；由 tick / deps 显式驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

function isNeedLogin(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** 请求桌面层打开登录窗口（openWindow 幂等：已存在则置前）。 */
function openLoginWindow() {
  getWindowManager().openWindow({
    id: "login",
    title: "平台登录",
    content: <LoginWindow />,
    defaultPosition: { x: 320, y: 140 },
    defaultSize: { width: 360, height: 440 },
    resizable: false,
  });
}

/** 区块卡片：细边框小圆角，信息密度优先。 */
function Card({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-background p-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-[13px] font-medium text-text-primary">{title}</h2>
        {hint && <p className="text-xs text-text-secondary">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/** 客户状态徽章：active → good，inactive → serious，其余 neutral。 */
function CustomerStatus({ status }: { status: string }) {
  if (status === "active") return <StatusBadge kind="good">启用</StatusBadge>;
  if (status === "inactive") return <StatusBadge kind="serious">停用</StatusBadge>;
  return <StatusBadge kind="neutral">{status}</StatusBadge>;
}

/* ============================================================================
   页面
   ========================================================================== */

export default function CustomersPage() {
  const custs = useApi<{ customers: CustomerRow[] }>(
    () => fetchIamGet("/master/customers?include_fixture=true"),
    [],
  );
  const dups = useApi<DupGroups>(() => fetchIamGet("/master/duplicates"), []);

  // ---- 新建客户表单 ----
  const [form, setForm] = useState({
    customer_id: "",
    name: "",
    is_test_fixture: false,
    test_run_id: "",
    retention_policy: "",
  });
  const [msg, setMsg] = useState<ActionMsg | null>(null);

  // ---- 搜索 / fixture 开关 / 分页（10/页，与 web 一致） ----
  const [q, setQ] = useState("");
  const [showFixture, setShowFixture] = useState(false);
  const [page, setPage] = useState(0);
  const PAGE = 10;

  // ---- 隔离概览（按客户展开） ----
  const [ov, setOv] = useState<OverviewBody | null>(null);
  const [ovBusy, setOvBusy] = useState(false);

  async function createCustomer() {
    setMsg(null);
    try {
      await fetchIamPost("master/customers", form);
      setMsg({ ok: true, text: "创建成功" });
      custs.reload();
    } catch (e) {
      setMsg({ ok: false, text: `创建失败：${errorMessageOf(e)}` });
    }
  }

  /** 停用 / 启用：可逆开关，服务端审计留痕；与 web 一致直接可调。 */
  async function toggleStatus(id: string, next: "active" | "inactive") {
    setMsg(null);
    try {
      await fetchIamPost(`master/customer/${id}/status`, { status: next });
      setMsg({ ok: true, text: `${id} 已${next === "inactive" ? "停用" : "启用"}` });
      custs.reload();
    } catch (e) {
      setMsg({ ok: false, text: `操作失败：${errorMessageOf(e)}` });
    }
  }

  async function loadOverview(id: string) {
    setOvBusy(true);
    try {
      setOv((await fetchIamGet(`master/customers/${id}/overview`)) as OverviewBody);
    } catch (e) {
      setOv({
        customer_id: id,
        runs: 0,
        tasks: 0,
        work_items: 0,
        events: 0,
        usage: [],
        error: errorMessageOf(e),
      });
    } finally {
      setOvBusy(false);
    }
  }

  if (isNeedLogin(custs.error)) {
    return (
      <div className="p-5 space-y-4">
        <PageHeader title="客户主数据" desc="客户 / 组织 / 保留策略" />
        <NeedLoginState onOpenLogin={openLoginWindow} />
      </div>
    );
  }

  // 默认只看 operational；勾选后包含 fixture（与 web 过滤一致）
  const all = (custs.data?.customers ?? []).filter(
    (cu) =>
      showFixture || (!cu.is_test_fixture && (cu.data_scope ?? "operational") === "operational"),
  );
  const hit = all.filter(
    (cu) => !q || cu.name.includes(q) || cu.customer_id.includes(q),
  );
  const pages = Math.max(1, Math.ceil(hit.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const shown = hit.slice(cur * PAGE, cur * PAGE + PAGE);

  const cols: ApiTableCol<CustomerRow>[] = [
    {
      key: "name",
      label: "客户",
      render: (cu) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <span>{cu.name}</span>
          <span className="text-xs text-text-secondary">{cu.customer_id}</span>
          {cu.is_test_fixture && <StatusBadge kind="warn">test fixture</StatusBadge>}
          {cu.test_run_id && (
            <span className="text-[11px] text-text-secondary">{cu.test_run_id}</span>
          )}
        </span>
      ),
    },
    { key: "retention_policy", label: "保留策略" },
    { key: "status", label: "状态", render: (cu) => <CustomerStatus status={cu.status} /> },
    {
      key: "actions",
      label: "操作",
      render: (cu) => (
        <span className="flex gap-1.5">
          <Button
            variant="secondary"
            size="sm"
            disabled={ovBusy}
            onClick={() => void loadOverview(cu.customer_id)}
          >
            隔离概览
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              void toggleStatus(cu.customer_id, cu.status === "active" ? "inactive" : "active")
            }
          >
            {cu.status === "active" ? "停用" : "启用"}
          </Button>
        </span>
      ),
    },
  ];

  const hasDups = (dups.data?.customers?.length ?? 0) > 0 || (dups.data?.skus?.length ?? 0) > 0;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="客户主数据"
        desc="客户 / 组织 / 保留策略；test fixture 显式标记，不得混入生产数据"
      />

      {/* 新建客户 */}
      <Card title="新建客户" hint="测试客户须先建 Test Run 上下文（服务端 fail-closed）">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="客户ID"
            placeholder="customer_id"
            className="w-36"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
          />
          <Input
            aria-label="客户名称"
            placeholder="名称"
            className="w-40"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Input
            aria-label="保留策略"
            placeholder="保留策略（半年/2年/7年）"
            className="w-52"
            value={form.retention_policy}
            onChange={(e) => setForm({ ...form, retention_policy: e.target.value })}
          />
          <label className="inline-flex cursor-pointer items-center gap-1 text-xs text-text-secondary">
            <input
              type="checkbox"
              className="accent-accent"
              checked={form.is_test_fixture}
              onChange={(e) => setForm({ ...form, is_test_fixture: e.target.checked })}
            />
            test fixture
          </label>
          {form.is_test_fixture && (
            <Input
              aria-label="Test Run ID"
              placeholder="test_run_id（必填）"
              className="w-56"
              value={form.test_run_id}
              onChange={(e) => setForm({ ...form, test_run_id: e.target.value })}
            />
          )}
          <Button
            size="sm"
            disabled={!form.customer_id || !form.name || (form.is_test_fixture && !form.test_run_id)}
            onClick={() => void createCustomer()}
          >
            创建
          </Button>
          {msg && <StatusBadge kind={msg.ok ? "good" : "serious"}>{msg.text}</StatusBadge>}
        </div>
      </Card>

      {/* 列表工具条：搜索 / fixture 开关 / 分页 */}
      <Card title="客户列表" hint="默认仅运营数据；测试数据显式开关">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Input
            aria-label="搜索客户"
            placeholder="搜索客户名称 / ID"
            className="w-60"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
          />
          <label className="inline-flex cursor-pointer items-center gap-1 text-xs text-text-secondary">
            <input
              type="checkbox"
              className="accent-accent"
              checked={showFixture}
              onChange={(e) => {
                setShowFixture(e.target.checked);
                setPage(0);
              }}
            />
            显示测试数据（fixture）
          </label>
          <span className="text-xs text-text-secondary tabular-nums">共 {hit.length} 条</span>
          <span className="flex items-center gap-1.5">
            <span className="text-xs text-text-secondary tabular-nums">
              第 {cur + 1}/{pages} 页
            </span>
            <Button variant="secondary" size="sm" disabled={cur === 0} onClick={() => setPage(cur - 1)}>
              上一页
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={cur >= pages - 1}
              onClick={() => setPage(cur + 1)}
            >
              下一页
            </Button>
          </span>
        </div>

        <ApiTable
          rows={shown}
          cols={cols}
          loading={custs.loading}
          error={custs.error}
          onRetry={custs.reload}
          emptyText="暂无客户"
          rowKey={(cu) => cu.customer_id}
        />

        {/* 隔离概览（runs / 任务 / Usage）：作用域隔离生效时以 serious 徽章呈现拒绝原因 */}
        {ov && (
          <div className="mt-3 space-y-1.5">
            <p className="text-xs font-medium text-text-secondary">
              隔离概览 · {ov.customer_id}
            </p>
            {ov.error ? (
              <StatusBadge kind="serious">概览拒绝：{ov.error}（作用域隔离生效）</StatusBadge>
            ) : (
              <KV
                items={[
                  { label: "runs", value: ov.runs },
                  { label: "识别任务", value: ov.tasks },
                  { label: "工作项", value: ov.work_items },
                  { label: "事件", value: ov.events },
                  {
                    label: "Usage",
                    value:
                      ov.usage.map((u) => `${u.unit}×${u.quantity}`).join("、") ||
                      "—",
                  },
                ]}
              />
            )}
          </div>
        )}
      </Card>

      {/* 合并建议（规范化重名，不自动合并） */}
      {hasDups && (
        <Card title="合并建议" hint="规范化重名，不自动合并">
          <div className="space-y-1">
            {(dups.data?.customers ?? []).map((g) => (
              <p key={g.name_key} className="text-xs text-text-secondary">
                客户疑似重复：{g.ids.join("、")}
              </p>
            ))}
            {(dups.data?.skus ?? []).map((g) => (
              <p key={g.name_key} className="text-xs text-text-secondary">
                SKU 疑似重复：{g.ids.join("、")}
              </p>
            ))}
          </div>
        </Card>
      )}

      {/* 合并建议接口错误不阻断主列表，仅给重试入口 */}
      {dups.error != null && !isNeedLogin(dups.error) && (
        <ErrorState message={errorMessageOf(dups.error)} onRetry={dups.reload} className="py-2" />
      )}
    </div>
  );
}
