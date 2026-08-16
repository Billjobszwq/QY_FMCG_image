/**
 * 账号与角色（IAM · /iam/accounts）—— v3 真实数据页面（P6）。
 *
 * 数据源（全部同源 /api/v1/*，无样本数据）：
 * —— GET  /iam/whoami        当前身份（KV 键值块）
 * —— GET  /iam/principals    身份列表（搜索 / 状态筛选 / 分页，客户端）
 * —— GET  /iam/roles         角色列表（内置 / 自定义）
 * —— GET  /iam/scopes        已注册 permission bundle（自定义角色勾选 + 模拟器）
 * —— POST iam/principals     开设账号（user / service_account / agent）
 * —— POST iam/grants         授权（角色 × 客户/项目作用域）
 * —— POST iam/roles          创建自定义角色（权限只从 bundle 组合）
 * —— GET  /iam/simulate      权限模拟器（能否 / 为什么）
 *
 * 状态纪律：401 → NeedLoginState（打开登录窗口）；网络错误 → ErrorState+重试；
 * 加载 → HedgehogLoader（ApiTable 内置）；空态 → HedgehogMascot（ApiTable 内置）。
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
import { Select } from "@/components/ui/select";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { getWindowManager } from "@/store/windowStore";

/* ============================================================================
   契约类型（与 web IamMaster.tsx 实际消费字段一致）
   ========================================================================== */

interface WhoamiBody {
  actor: string;
  session_role: string;
  roles: string[];
  /** null = 全部（平台角色） */
  visible_customers: string[] | null;
}

interface PrincipalRow {
  principal_id: string;
  username: string;
  kind: string;
  display_name: string;
  status: string;
}

interface RoleRow {
  role_id: string;
  name: string;
  builtin: boolean;
  scopes: string[];
}

interface SimulateResult {
  allowed: boolean;
  reasons?: string[];
}

/* ============================================================================
   轻量数据 hook：loading / error / reload（tick 驱动；deps 由调用方声明键）
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

/** 401 → 需要登录（数据红线）。 */
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

/* ============================================================================
   局部小件：卡片 / 操作回执 / 分页器
   ========================================================================== */

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

interface ActionMsg {
  ok: boolean;
  text: string;
}

/** 写操作回执：good / serious 徽章（状态一律 StatusBadge）。 */
function ActionBadge({ msg }: { msg: ActionMsg | null }) {
  if (!msg) return null;
  return <StatusBadge kind={msg.ok ? "good" : "serious"}>{msg.text}</StatusBadge>;
}

function Pager({
  page,
  pages,
  onPage,
}: {
  page: number;
  pages: number;
  onPage: (p: number) => void;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-xs text-text-secondary tabular-nums">
        第 {page + 1}/{pages} 页
      </span>
      <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => onPage(page - 1)}>
        上一页
      </Button>
      <Button
        variant="secondary"
        size="sm"
        disabled={page >= pages - 1}
        onClick={() => onPage(page + 1)}
      >
        下一页
      </Button>
    </span>
  );
}

/** 身份状态徽章：active → good，disabled → serious，其余 neutral。 */
function PrincipalStatus({ status }: { status: string }) {
  if (status === "active") return <StatusBadge kind="good">启用</StatusBadge>;
  if (status === "disabled") return <StatusBadge kind="serious">停用</StatusBadge>;
  return <StatusBadge kind="neutral">{status}</StatusBadge>;
}

/* 内置角色兜底（服务端 roles 拉取前供授权下拉使用） */
const BUILTIN_ROLES = [
  "owner",
  "platform_admin",
  "customer_admin",
  "project_manager",
  "survey_designer",
  "field_manager",
  "reviewer",
  "analyst",
  "finance_operator",
  "read_only",
  "agent_service",
];

/* ============================================================================
   页面
   ========================================================================== */

export default function AccountsPage() {
  // ---- 读侧 ----
  const whoami = useApi<WhoamiBody>(() => fetchIamGet("/iam/whoami"), []);
  const principals = useApi<{ principals: PrincipalRow[] }>(
    () => fetchIamGet("/iam/principals"),
    [],
  );
  const rolesApi = useApi<{ roles: RoleRow[] }>(() => fetchIamGet("/iam/roles"), []);
  const scopesApi = useApi<{ scopes: string[] }>(() => fetchIamGet("/iam/scopes"), []);

  // ---- 身份列表：搜索 / 状态筛选 / 分页（客户端） ----
  const [pq, setPq] = useState("");
  const [pStatus, setPStatus] = useState("");
  const [pPage, setPPage] = useState(0);

  // ---- 写侧表单 ----
  const [form, setForm] = useState({
    kind: "user",
    username: "",
    display_name: "",
    password: "",
  });
  const [grant, setGrant] = useState({
    username: "",
    role: "read_only",
    customer_id: "",
    project_id: "",
  });
  const [newRole, setNewRole] = useState({ name: "", description: "", scopes: [] as string[] });
  const [sim, setSim] = useState({ username: "", scope: "survey.read", customer_id: "" });
  const [simResult, setSimResult] = useState<SimulateResult | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const [msg, setMsg] = useState<ActionMsg | null>(null);

  const roleNames = rolesApi.data ? rolesApi.data.roles.map((r) => r.name) : BUILTIN_ROLES;
  const scopeList = scopesApi.data?.scopes ?? [];

  /** 写操作统一入口：成功回执 + 刷新身份列表。 */
  async function doAction(name: string, fn: () => Promise<unknown>) {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: `${name}成功` });
      principals.reload();
    } catch (e) {
      setMsg({ ok: false, text: `${name}失败：${errorMessageOf(e)}` });
    }
  }

  async function runSimulate() {
    setSimBusy(true);
    try {
      const q = new URLSearchParams({
        username: sim.username,
        scope: sim.scope,
        customer_id: sim.customer_id,
      });
      setSimResult((await fetchIamGet(`/iam/simulate?${q}`)) as SimulateResult);
    } catch (e) {
      setSimResult({ allowed: false, reasons: [errorMessageOf(e)] });
    } finally {
      setSimBusy(false);
    }
  }

  // ---- 401：整页切“需要登录” ----
  const fatal = [whoami.error, principals.error].find(isNeedLogin);
  if (fatal) {
    return (
      <div className="p-5 space-y-4">
        <PageHeader title="账号与角色" desc="IAM 身份 / 角色 / 作用域（fail-closed）" />
        <NeedLoginState onOpenLogin={openLoginWindow} />
      </div>
    );
  }

  const principalCols: ApiTableCol<PrincipalRow>[] = [
    { key: "username", label: "username" },
    { key: "kind", label: "类型" },
    { key: "display_name", label: "显示名" },
    { key: "status", label: "状态", render: (r) => <PrincipalStatus status={r.status} /> },
  ];

  const roleCols: ApiTableCol<RoleRow>[] = [
    { key: "name", label: "角色" },
    { key: "builtin", label: "类型", render: (r) => (r.builtin ? "内置" : "自定义") },
    {
      key: "scopes",
      label: "权限",
      render: (r) =>
        r.scopes.length > 0 ? (
          <span className="text-xs text-text-secondary">{r.scopes.join("、")}</span>
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
  ];

  // 身份列表过滤与分页（20/页，与 web 一致）
  const allPrincipals = principals.data?.principals ?? [];
  const hit = allPrincipals.filter(
    (p) =>
      (!pq || p.username.includes(pq) || (p.display_name ?? "").includes(pq)) &&
      (!pStatus || p.status === pStatus),
  );
  const pages = Math.max(1, Math.ceil(hit.length / 20));
  const cur = Math.min(pPage, pages - 1);
  const shown = hit.slice(cur * 20, cur * 20 + 20);

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="账号与角色"
        desc="用户 / 服务账号 / Agent 独立身份；permission bundle 组合角色；tenant / customer / project 作用域（fail-closed）"
      />

      {/* 当前身份（whoami） */}
      {whoami.error && !isNeedLogin(whoami.error) ? (
        <ErrorState message={errorMessageOf(whoami.error)} onRetry={whoami.reload} />
      ) : whoami.data ? (
        <KV
          items={[
            { label: "当前身份", value: whoami.data.actor },
            { label: "session 角色", value: whoami.data.session_role },
            {
              label: "IAM 角色",
              value: whoami.data.roles.join("、") || <span className="text-text-secondary">—</span>,
            },
            {
              label: "客户作用域",
              value:
                whoami.data.visible_customers === null
                  ? "全部（平台角色）"
                  : whoami.data.visible_customers.join("、") || "无",
            },
          ]}
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 开设账号 + 授权 */}
        <Card title="开设账号 / 授权" hint="user · service_account · agent">
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <Select
                aria-label="身份类型"
                className="w-44"
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}
              >
                <option value="user">user</option>
                <option value="service_account">service_account</option>
                <option value="agent">agent（不得口令登录）</option>
              </Select>
              <Input
                aria-label="用户名"
                placeholder="username"
                className="w-36"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
              <Input
                aria-label="显示名"
                placeholder="显示名"
                className="w-32"
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              />
              <Input
                aria-label="口令"
                type="password"
                placeholder="口令（user 必填）"
                className="w-40"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
              <Button
                size="sm"
                disabled={!form.username}
                onClick={() => void doAction("开设账号", () => fetchIamPost("iam/principals", form))}
              >
                创建
              </Button>
            </div>

            <p className="pt-1 text-xs font-medium text-text-secondary">
              授权（角色 × 客户 / 项目作用域）
            </p>
            <div className="flex flex-wrap gap-2">
              <Input
                aria-label="授权对象"
                placeholder="username"
                className="w-36"
                value={grant.username}
                onChange={(e) => setGrant({ ...grant, username: e.target.value })}
              />
              <Select
                aria-label="角色"
                className="w-40"
                value={grant.role}
                onChange={(e) => setGrant({ ...grant, role: e.target.value })}
              >
                {roleNames.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
              <Input
                aria-label="客户作用域"
                placeholder="customer_id（空=租户级）"
                className="w-44"
                value={grant.customer_id}
                onChange={(e) => setGrant({ ...grant, customer_id: e.target.value })}
              />
              <Input
                aria-label="项目作用域"
                placeholder="project_id（可空）"
                className="w-36"
                value={grant.project_id}
                onChange={(e) => setGrant({ ...grant, project_id: e.target.value })}
              />
              <Button
                size="sm"
                disabled={!grant.username}
                onClick={() => void doAction("授权", () => fetchIamPost("iam/grants", grant))}
              >
                授权
              </Button>
            </div>
            <ActionBadge msg={msg} />
          </div>
        </Card>

        {/* 权限模拟器 */}
        <Card title="权限模拟器" hint="能否 / 为什么">
          <div className="flex flex-wrap gap-2">
            <Input
              aria-label="模拟对象"
              placeholder="username"
              className="w-36"
              value={sim.username}
              onChange={(e) => setSim({ ...sim, username: e.target.value })}
            />
            <Select
              aria-label="模拟 scope"
              className="w-44"
              value={sim.scope}
              onChange={(e) => setSim({ ...sim, scope: e.target.value })}
            >
              {(scopeList.length > 0 ? scopeList : ["survey.read"]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <Input
              aria-label="模拟客户"
              placeholder="customer_id（可空）"
              className="w-44"
              value={sim.customer_id}
              onChange={(e) => setSim({ ...sim, customer_id: e.target.value })}
            />
            <Button size="sm" disabled={!sim.username || simBusy} onClick={() => void runSimulate()}>
              {simBusy ? "模拟中…" : "模拟"}
            </Button>
          </div>
          {simResult && (
            <div className="mt-2 space-y-1">
              <StatusBadge kind={simResult.allowed ? "good" : "serious"}>
                {simResult.allowed ? "允许" : "拒绝"}
              </StatusBadge>
              {(simResult.reasons ?? []).map((r, i) => (
                <p key={i} className="text-xs text-text-secondary">
                  · {r}
                </p>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* 自定义角色 + 角色列表 */}
      <Card title="自定义角色" hint="权限只从已注册 permission bundle 组合">
        <div className="flex flex-wrap gap-2">
          <Input
            aria-label="角色名"
            placeholder="角色名"
            className="w-40"
            value={newRole.name}
            onChange={(e) => setNewRole({ ...newRole, name: e.target.value })}
          />
          <Input
            aria-label="角色描述"
            placeholder="描述"
            className="w-52"
            value={newRole.description}
            onChange={(e) => setNewRole({ ...newRole, description: e.target.value })}
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {scopeList.map((s) => (
            <label
              key={s}
              className="inline-flex cursor-pointer items-center gap-1 text-xs text-text-secondary"
            >
              <input
                type="checkbox"
                className="accent-accent"
                checked={newRole.scopes.includes(s)}
                onChange={(e) =>
                  setNewRole({
                    ...newRole,
                    scopes: e.target.checked
                      ? [...newRole.scopes, s]
                      : newRole.scopes.filter((x) => x !== s),
                  })
                }
              />
              {s}
            </label>
          ))}
          {scopeList.length === 0 && !scopesApi.loading && (
            <span className="text-xs text-text-secondary">暂无已注册 scope</span>
          )}
        </div>
        <Button
          size="sm"
          className="mt-2"
          disabled={!newRole.name || newRole.scopes.length === 0}
          onClick={() =>
            void doAction("创建角色", async () => {
              await fetchIamPost("iam/roles", newRole);
              rolesApi.reload();
            })
          }
        >
          创建角色
        </Button>
        <div className="mt-3">
          <ApiTable
            rows={rolesApi.data?.roles ?? []}
            cols={roleCols}
            loading={rolesApi.loading}
            error={rolesApi.error}
            onRetry={rolesApi.reload}
            emptyText="暂无角色"
            rowKey={(r) => r.role_id}
          />
        </div>
      </Card>

      {/* 身份列表（搜索 / 状态筛选 / 分页） */}
      <Card title="身份列表" hint="默认仅运营身份；测试身份见测试与证据中心">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Input
            aria-label="搜索身份"
            placeholder="搜索用户名 / 显示名"
            className="w-56"
            value={pq}
            onChange={(e) => {
              setPq(e.target.value);
              setPPage(0);
            }}
          />
          <Select
            aria-label="状态筛选"
            className="w-32"
            value={pStatus}
            onChange={(e) => {
              setPStatus(e.target.value);
              setPPage(0);
            }}
          >
            <option value="">全部状态</option>
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </Select>
          <span className="text-xs text-text-secondary tabular-nums">共 {hit.length} 条</span>
          <Pager page={cur} pages={pages} onPage={setPPage} />
        </div>
        <ApiTable
          rows={shown}
          cols={principalCols}
          loading={principals.loading}
          error={principals.error}
          onRetry={principals.reload}
          emptyText="尚无匹配的 IAM 身份"
          rowKey={(r) => r.principal_id}
        />
      </Card>
    </div>
  );
}
