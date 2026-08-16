/**
 * 项目主数据（/master/projects）—— v3 真实数据页面（P6）。
 *
 * 数据源（全部同源 /api/v1/*，无样本数据）：
 * —— GET  /master/customers                    客户下拉（按客户作用域访问）
 * —— GET  master/projects?customer_id={cid}    指定客户的项目列表（选中后才拉取）
 * —— POST master/projects                      新建项目（project_id × customer_id × 名称）
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
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { getWindowManager } from "@/store/windowStore";

/* ============================================================================
   契约类型（与 web IamMaster.tsx 实际消费字段一致）
   ========================================================================== */

interface CustomerRow {
  customer_id: string;
  name: string;
}

interface ProjectRow {
  project_id: string;
  name: string;
  status: string;
}

interface ActionMsg {
  ok: boolean;
  text: string;
}

/* ============================================================================
   轻量数据 hook（与 P6 其余页面同构；fetcher=null 时不发请求）
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

/** 项目状态徽章：active → good，其余 neutral（后端词表未知，保守映射）。 */
function ProjectStatus({ status }: { status: string }) {
  if (status === "active") return <StatusBadge kind="good">进行中</StatusBadge>;
  if (status === "closed" || status === "archived") {
    return <StatusBadge kind="neutral">已关闭</StatusBadge>;
  }
  return <StatusBadge kind="neutral">{status}</StatusBadge>;
}

/* ============================================================================
   页面
   ========================================================================== */

export default function ProjectsPage() {
  const custs = useApi<{ customers: CustomerRow[] }>(
    () => fetchIamGet("/master/customers"),
    [],
  );

  const [cid, setCid] = useState("");
  // 未选客户不发请求（fetcher=null）
  const projs = useApi<{ projects: ProjectRow[] }>(
    cid ? () => fetchIamGet(`master/projects?customer_id=${cid}`) : null,
    [cid],
  );

  const [form, setForm] = useState({ project_id: "", customer_id: "", name: "" });
  const [msg, setMsg] = useState<ActionMsg | null>(null);

  async function createProject() {
    setMsg(null);
    try {
      await fetchIamPost("master/projects", form);
      setMsg({ ok: true, text: "创建成功" });
      projs.reload();
    } catch (e) {
      setMsg({ ok: false, text: `创建失败：${errorMessageOf(e)}` });
    }
  }

  if (isNeedLogin(custs.error) || isNeedLogin(projs.error)) {
    return (
      <div className="p-5 space-y-4">
        <PageHeader title="项目主数据" desc="项目关联客户、SKU 范围与预算" />
        <NeedLoginState onOpenLogin={openLoginWindow} />
      </div>
    );
  }

  const cols: ApiTableCol<ProjectRow>[] = [
    { key: "project_id", label: "project_id" },
    { key: "name", label: "名称" },
    { key: "status", label: "状态", render: (p) => <ProjectStatus status={p.status} /> },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="项目主数据"
        desc="项目关联客户、SKU 范围与预算；按客户作用域访问"
      />

      {/* 新建项目 */}
      <Card title="新建项目">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="项目ID"
            placeholder="project_id"
            className="w-40"
            value={form.project_id}
            onChange={(e) => setForm({ ...form, project_id: e.target.value })}
          />
          <Input
            aria-label="所属客户"
            placeholder="customer_id"
            className="w-40"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
          />
          <Input
            aria-label="项目名称"
            placeholder="名称"
            className="w-48"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Button
            size="sm"
            disabled={!form.project_id || !form.customer_id || !form.name}
            onClick={() => void createProject()}
          >
            创建
          </Button>
          {msg && <StatusBadge kind={msg.ok ? "good" : "serious"}>{msg.text}</StatusBadge>}
        </div>
      </Card>

      {/* 按客户查看 */}
      <Card title="按客户查看" hint="项目按客户作用域访问">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Select
            aria-label="选择客户"
            className="w-72"
            value={cid}
            onChange={(e) => setCid(e.target.value)}
          >
            <option value="">选择客户…</option>
            {(custs.data?.customers ?? []).map((cu) => (
              <option key={cu.customer_id} value={cu.customer_id}>
                {cu.name}（{cu.customer_id}）
              </option>
            ))}
          </Select>
          <span className="text-xs text-text-secondary tabular-nums">
            {projs.data ? `共 ${projs.data.projects.length} 个项目` : ""}
          </span>
        </div>

        {/* 客户下拉自身的错误单独呈现，不与项目表混 */}
        {custs.error != null && !isNeedLogin(custs.error) && (
          <ErrorState
            message={`客户列表加载失败：${errorMessageOf(custs.error)}`}
            onRetry={custs.reload}
            className="py-2"
          />
        )}

        <ApiTable
          rows={projs.data?.projects ?? []}
          cols={cols}
          loading={projs.loading}
          error={projs.error}
          onRetry={projs.reload}
          emptyText={cid ? "该客户暂无项目" : "请先选择客户"}
          rowKey={(p) => p.project_id}
        />
      </Card>
    </div>
  );
}
