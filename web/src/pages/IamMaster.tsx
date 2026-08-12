// ABOSV2 Phase D：账号与权限（iam）+ 客户与主数据（master）页面。
// 全部来自真实 API；作用域 fail-closed；test fixture 显式标记。
import { useEffect, useState } from "react";
import { iamGet, iamPost } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader }
  from "../platform/components";

function useLoad<T>(path: string | null): {
  data: T | null; err: string | null; reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    iamGet(path).then(setData).catch(
      (e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [path, tick]);
  return { data, err, reload: () => { setErr(null); setTick(t => t + 1); } };
}

// ---- 账号与角色 ----
export function IamAccounts() {
  const me = useLoad<any>("/iam/whoami");
  const principals = useLoad<any>("/iam/principals");
  // SI4（P2-002）：身份列表搜索/状态筛选/分页状态
  const [pq, setPq] = useState("");
  const [pStatus, setPStatus] = useState("");
  const [pPage, setPPage] = useState(0);
  const rolesApi = useLoad<any>("/iam/roles");
  const scopesApi = useLoad<any>("/iam/scopes");
  const [form, setForm] = useState({ kind: "user", username: "",
    display_name: "", password: "" });
  const [grant, setGrant] = useState({ username: "", role: "read_only",
    customer_id: "", project_id: "" });
  const [newRole, setNewRole] = useState({ name: "", description: "",
    scopes: [] as string[] });
  const [sim, setSim] = useState({ username: "", scope: "survey.read",
    customer_id: "" });
  const [simResult, setSimResult] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const builtinRoles = ["owner", "platform_admin", "customer_admin",
    "project_manager", "survey_designer", "field_manager", "reviewer",
    "analyst", "finance_operator", "read_only", "agent_service"];
  const roleNames = rolesApi.data
    ? rolesApi.data.roles.map((r: any) => r.name) : builtinRoles;

  const doAction = async (name: string, fn: () => Promise<any>) => {
    setMsg(null);
    try { await fn(); setMsg(`${name}成功`); principals.reload(); }
    catch (e) { setMsg(`${name}失败：${e instanceof Error ? e.message : e}`); }
  };

  return (
    <>
      <PageHeader title="账号与角色"
        desc="用户/服务账号/Agent 独立身份；permission bundle 组合角色；tenant/customer/project 作用域（fail-closed）" />
      {me.data && (
        <div className="card">
          <h3>当前身份（whoami）</h3>
          <p className="v">{me.data.actor} · session 角色
            {me.data.session_role} · IAM 角色
            {me.data.roles.join("、") || "—"} · 客户作用域
            {me.data.visible_customers === null ? "全部（平台角色）"
              : ((me.data.visible_customers ?? []).join("、") || "无")}</p>
        </div>
      )}
      <div className="card">
        <h3>开设账号（user / service_account / agent）</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <select value={form.kind} aria-label="身份类型"
            onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="user">user</option>
            <option value="service_account">service_account</option>
            <option value="agent">agent（独立身份，不得口令登录）</option>
          </select>
          <input placeholder="username" aria-label="用户名"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input placeholder="显示名" aria-label="显示名"
            value={form.display_name}
            onChange={(e) => setForm({ ...form,
              display_name: e.target.value })} />
          <input placeholder="口令（user 必填）" aria-label="口令"
            type="password" value={form.password}
            onChange={(e) => setForm({ ...form,
              password: e.target.value })} />
          <button className="btn small primary"
            onClick={() => doAction("开设账号", () =>
              iamPost("iam/principals", form))}>创建</button>
        </div>
        <h3 style={{ marginTop: 12 }}>授权（角色 × 客户/项目作用域）</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input placeholder="username" aria-label="授权对象"
            value={grant.username}
            onChange={(e) => setGrant({ ...grant,
              username: e.target.value })} />
          <select value={grant.role} aria-label="角色"
            onChange={(e) => setGrant({ ...grant, role: e.target.value })}>
            {roleNames.map((r: string) => <option key={r} value={r}>{r}</option>)}
          </select>
          <input placeholder="customer_id（空=租户级）"
            aria-label="客户作用域" value={grant.customer_id}
            onChange={(e) => setGrant({ ...grant,
              customer_id: e.target.value })} />
          <input placeholder="project_id（可空）" aria-label="项目作用域"
            value={grant.project_id}
            onChange={(e) => setGrant({ ...grant,
              project_id: e.target.value })} />
          <button className="btn small primary"
            onClick={() => doAction("授权", () =>
              iamPost("iam/grants", grant))}>授权</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>

      {/* ABOSV3-P1-008：自定义角色 + 权限模拟器 */}
      <div className="grid" style={{ gridTemplateColumns:
        "repeat(auto-fit, minmax(340px, 1fr))" }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>自定义角色（权限只从已注册 bundle 组合）</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input placeholder="角色名" aria-label="角色名"
              value={newRole.name}
              onChange={(e) => setNewRole({ ...newRole,
                name: e.target.value })} />
            <input placeholder="描述" aria-label="角色描述"
              value={newRole.description}
              onChange={(e) => setNewRole({ ...newRole,
                description: e.target.value })} />
          </div>
          <div style={{ marginTop: 8, display: "flex",
            flexWrap: "wrap", gap: 6 }}>
            {(scopesApi.data?.scopes ?? []).map((s: string) => (
              <label key={s} className="v"
                style={{ fontSize: 12, display: "inline-flex",
                  gap: 4, alignItems: "center" }}>
                <input type="checkbox" checked={newRole.scopes.includes(s)}
                  onChange={(e) => setNewRole({ ...newRole,
                    scopes: e.target.checked
                      ? [...newRole.scopes, s]
                      : newRole.scopes.filter(x => x !== s) })} />
                {s}</label>))}
          </div>
          <button className="btn small primary" style={{ marginTop: 8 }}
            disabled={!newRole.name || newRole.scopes.length === 0}
            onClick={() => doAction("创建角色", async () => {
              await iamPost("iam/roles", newRole);
              rolesApi.reload();
            })}>创建角色</button>
          <h3 style={{ marginTop: 12 }}>角色列表</h3>
          {rolesApi.data && (
            <table className="table">
              <thead><tr><th>角色</th><th>类型</th><th>权限</th></tr></thead>
              <tbody>
                {rolesApi.data.roles.map((r: any) => (
                  <tr key={r.role_id}>
                    <td data-label="角色">{r.name}</td>
                    <td data-label="类型">{r.builtin ? "内置"
                      : "自定义"}</td>
                    <td data-label="权限" className="v">
                      {r.scopes.join("、") || "—"}</td>
                  </tr>))}
              </tbody>
            </table>)}
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>权限模拟器（能否/为什么）</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input placeholder="username" aria-label="模拟对象"
              value={sim.username}
              onChange={(e) => setSim({ ...sim,
                username: e.target.value })} />
            <select value={sim.scope} aria-label="模拟 scope"
              onChange={(e) => setSim({ ...sim, scope: e.target.value })}>
              {(scopesApi.data?.scopes ?? ["survey.read"]).map(
                (s: string) => <option key={s} value={s}>{s}</option>)}
            </select>
            <input placeholder="customer_id（可空）" aria-label="模拟客户"
              value={sim.customer_id}
              onChange={(e) => setSim({ ...sim,
                customer_id: e.target.value })} />
            <button className="btn small primary"
              disabled={!sim.username}
              onClick={async () => {
                try {
                  const q = new URLSearchParams({ username: sim.username,
                    scope: sim.scope, customer_id: sim.customer_id });
                  setSimResult(await iamGet(`/iam/simulate?${q}`));
                } catch (e) {
                  setSimResult({ allowed: false,
                    reasons: [String(e)] });
                }
              }}>模拟</button>
          </div>
          {simResult && (
            <div style={{ marginTop: 10 }}>
              <p className="v" style={{ fontWeight: 600,
                color: simResult.allowed ? "var(--ok)" : "var(--err)" }}>
                {simResult.allowed ? "✓ 允许" : "✗ 拒绝"}</p>
              {simResult.reasons?.map((r: string, i: number) => (
                <p key={i} className="v">· {r}</p>))}
            </div>)}
        </div>
      </div>
      <div className="card">
        <h3>身份列表</h3>
        {principals.err && <ErrorState message={principals.err}
          onRetry={principals.reload} />}
        {!principals.data && !principals.err && <Loading />}
        {principals.data && (() => {
          const all: any[] = principals.data.principals ?? [];
          const hit = all.filter((p: any) =>
            (!pq || (p.username || "").includes(pq)
              || (p.display_name || "").includes(pq))
            && (!pStatus || p.status === pStatus));
          const pages = Math.max(1, Math.ceil(hit.length / 20));
          const cur = Math.min(pPage, pages - 1);
          const shown = hit.slice(cur * 20, cur * 20 + 20);
          return (<>
            {/* SI4（P2-002）：搜索/状态筛选/分页 */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
              alignItems: "center", marginBottom: 8 }}>
              <input placeholder="搜索用户名/显示名" aria-label="搜索身份"
                value={pq} onChange={(e) => { setPq(e.target.value);
                  setPPage(0); }} style={{ maxWidth: 220 }} />
              <select aria-label="状态筛选" value={pStatus}
                onChange={(e) => { setPStatus(e.target.value);
                  setPPage(0); }}>
                <option value="">全部状态</option>
                <option value="active">active</option>
                <option value="disabled">disabled</option>
              </select>
              <span className="muted" style={{ fontSize: 12 }}>
                共 {hit.length} 条 · 第 {cur + 1}/{pages} 页（默认仅
                运营身份；测试身份见测试与证据中心）</span>
              <button className="btn small" disabled={cur === 0}
                onClick={() => setPPage(cur - 1)}>上一页</button>
              <button className="btn small" disabled={cur >= pages - 1}
                onClick={() => setPPage(cur + 1)}>下一页</button>
            </div>
            {hit.length === 0
              ? <EmptyState title="尚无匹配的 IAM 身份" />
              : (
                <table className="table">
                  <thead><tr><th>username</th><th>类型</th>
                    <th>显示名</th><th>状态</th></tr></thead>
                  <tbody>
                    {shown.map((p: any) => (
                      <tr key={p.principal_id}>
                        <td data-label="username">{p.username}</td>
                        <td data-label="类型">{p.kind}</td>
                        <td data-label="显示名">{p.display_name}</td>
                        <td data-label="状态">{p.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </>);
        })()}
      </div>
    </>
  );
}

// ---- 审计与批准矩阵 ----
export function IamAudit() {
  const audit = useLoad<any>("/iam/audit");
  const [action, setAction] = useState("production.switch");
  const [check, setCheck] = useState<any | null>(null);
  return (
    <>
      <PageHeader title="审计与批准矩阵"
        desc="append-only 审计事件；高风险动作只能由矩阵指定角色批准" />
      <div className="card">
        <h3>批准矩阵检查</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ flex: 1 }} value={action} aria-label="动作"
            onChange={(e) => setAction(e.target.value)} />
          <button className="btn small"
            onClick={async () => {
              try {
                setCheck(await iamPost("iam/approval-check",
                  { action }));
              } catch (e) { setCheck({ error: String(e) }); }
            }}>检查我是否可批准</button>
        </div>
        {check && <p className="v" style={{ marginTop: 8 }}>
          {check.error ? `失败：${check.error}`
            : `${check.action} → ${check.allowed ? "允许" : "拒绝"
            }（当前身份 ${check.username}）`}</p>}
      </div>
      <div className="card">
        <h3>审计事件（append-only）</h3>
        {audit.err && <ErrorState message={audit.err}
          onRetry={audit.reload} />}
        {!audit.data && !audit.err && <Loading />}
        {audit.data && (audit.data.events.length === 0
          ? <EmptyState title="暂无审计事件" />
          : (
            <table className="table">
              <thead><tr><th>时间</th><th>操作者</th><th>动作</th>
                <th>资源</th><th>客户</th></tr></thead>
              <tbody>
                {audit.data.events.slice(0, 50).map((e: any) => (
                  <tr key={e.audit_id}>
                    <td data-label="时间" className="v"
                      style={{ fontSize: 11 }}>
                      {e.occurred_at?.slice(0, 19)}</td>
                    <td data-label="操作者">{e.actor_id}</td>
                    <td data-label="动作">{e.action}</td>
                    <td data-label="资源" className="v">{e.resource}</td>
                    <td data-label="客户">{e.customer_id || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
      </div>
    </>
  );
}

// ---- 客户库 ----
export function MasterCustomers() {
  const custs = useLoad<any>("/master/customers?include_fixture=true");
  const dups = useLoad<any>("/master/duplicates");
  const [form, setForm] = useState({ customer_id: "", name: "",
    is_test_fixture: false, test_run_id: "", retention_policy: "" });
  const [ov, setOv] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  // SI3（指令七.2）：搜索/分页/scope 筛选；默认只看 operational
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [showFixture, setShowFixture] = useState(false);
  const PAGE = 10;
  const setStatus = async (id: string, status: string) => {
    try {
      await iamPost(`master/customer/${id}/status`, { status });
      setMsg(`${id} 已${status === "inactive" ? "停用" : "启用"}`);
      custs.reload();
    } catch (e) {
      setMsg(`操作失败：${e instanceof Error ? e.message : e}`);
    }
  };
  return (
    <>
      <PageHeader title="客户库"
        desc="客户/组织/保留策略；test fixture 显式标记，不得混入生产数据" />
      <div className="card">
        <h3>新建客户</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input placeholder="customer_id" aria-label="客户ID"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form,
              customer_id: e.target.value })} />
          <input placeholder="名称" aria-label="客户名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="保留策略（半年/2年/7年）"
            aria-label="保留策略" value={form.retention_policy}
            onChange={(e) => setForm({ ...form,
              retention_policy: e.target.value })} />
          <label style={{ fontSize: 12, display: "flex",
            alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={form.is_test_fixture}
              onChange={(e) => setForm({ ...form,
                is_test_fixture: e.target.checked })} />
            test fixture
          </label>
          {form.is_test_fixture && (
            <input placeholder="test_run_id（测试中心上下文，必填）"
              aria-label="Test Run ID" value={form.test_run_id}
              style={{ minWidth: 220 }}
              onChange={(e) => setForm({ ...form,
                test_run_id: e.target.value })} />
          )}
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("master/customers", form);
              setMsg("创建成功"); custs.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>创建</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          运营客户默认不勾选测试标记；测试客户必须先在建“测试与证据
          中心”创建 Test Run 上下文并绑定 test_run_id（服务端
          fail-closed，无 test_run 的测试客户会被 409 拒绝）。
        </p>
      </div>
      {custs.err && <ErrorState message={custs.err}
        onRetry={custs.reload} />}
      {!custs.data && !custs.err && <Loading />}
      {custs.data && (() => {
        const all = (custs.data.customers ?? []).filter((cu: any) =>
          showFixture || (!cu.is_test_fixture
            && (cu.data_scope ?? "operational") === "operational"));
        const hit = all.filter((cu: any) => !q
          || cu.name?.includes(q) || cu.customer_id?.includes(q));
        const pages = Math.max(1, Math.ceil(hit.length / PAGE));
        const cur = Math.min(page, pages - 1);
        return (
          <div className="card">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
              alignItems: "center" }}>
              <input placeholder="搜索客户名称 / ID" aria-label="搜索客户"
                value={q} onChange={(e) => { setQ(e.target.value);
                  setPage(0); }} style={{ maxWidth: 240 }} />
              <label style={{ fontSize: 12, display: "flex",
                alignItems: "center", gap: 4 }}>
                <input type="checkbox" checked={showFixture}
                  onChange={(e) => { setShowFixture(e.target.checked);
                    setPage(0); }} />
                显示测试数据（fixture）
              </label>
              <span className="muted" style={{ fontSize: 12 }}>
                共 {hit.length} 条 · 第 {cur + 1}/{pages} 页</span>
              <button className="btn small" disabled={cur === 0}
                onClick={() => setPage(cur - 1)}>上一页</button>
              <button className="btn small" disabled={cur >= pages - 1}
                onClick={() => setPage(cur + 1)}>下一页</button>
            </div>
          </div>);
      })()}
      {custs.data && (() => {
        const all = (custs.data.customers ?? []).filter((cu: any) =>
          showFixture || (!cu.is_test_fixture
            && (cu.data_scope ?? "operational") === "operational"));
        const hit = all.filter((cu: any) => !q
          || cu.name?.includes(q) || cu.customer_id?.includes(q));
        const cur = Math.min(page, Math.max(0,
          Math.ceil(hit.length / PAGE) - 1));
        const shown = hit.slice(cur * PAGE, cur * PAGE + PAGE);
        if (hit.length === 0) return <EmptyState title="暂无客户" />;
        return shown.map((cu: any) => (
          <div className="card" key={cu.customer_id}>
            <h3>{cu.name} <span className="v">{cu.customer_id}</span>
              {cu.is_test_fixture && <span className="badge warn"
                style={{ marginLeft: 8 }}>test fixture</span>}
              {cu.test_run_id ? <span className="badge muted"
                style={{ marginLeft: 8 }}>{cu.test_run_id}</span>
                : null}</h3>
            <p className="v">保留策略：{cu.retention_policy || "—"} ·
              状态 {cu.status}</p>
            <button className="btn small" onClick={async () => {
              try {
                setOv(await iamGet(
                  `master/customers/${cu.customer_id}/overview`));
              } catch (e) {
                setOv({ error: e instanceof Error ? e.message : e });
              }
            }}>隔离概览（runs/任务/Usage）</button>{" "}
            <button className="btn small"
              onClick={() => setStatus(cu.customer_id,
                cu.status === "active" ? "inactive" : "active")}>
              {cu.status === "active" ? "停用" : "启用"}</button>
            {ov && ov.customer_id === cu.customer_id && (
              ov.error
                ? <p className="v" style={{ color: "var(--err)" }}>
                    概览拒绝：{ov.error}（作用域隔离生效）</p>
                : (
                  <div className="detail-kv" style={{ marginTop: 8 }}>
                    <b>runs</b><span>{ov.runs}</span>
                    <b>识别任务</b><span>{ov.tasks}</span>
                    <b>工作项</b><span>{ov.work_items}</span>
                    <b>事件</b><span>{ov.events}</span>
                    <b>Usage</b><span>{ov.usage.map((u: any) =>
                      `${u.unit}×${u.quantity}`).join("、") || "—"}</span>
                  </div>
                )
            )}
          </div>
        ));
      })()}
      {dups.data && (dups.data.customers?.length > 0
        || dups.data.skus?.length > 0) && (
        <div className="card">
          <h3>合并建议（规范化重名，不自动合并）</h3>
          {dups.data.customers.map((g: any) => (
            <p key={g.name_key} className="v">客户疑似重复：
              {g.ids.join("、")}</p>))}
          {dups.data.skus.map((g: any) => (
            <p key={g.name_key} className="v">SKU 疑似重复：
              {g.ids.join("、")}</p>))}
        </div>)}
    </>
  );
}

// ---- 项目库 ----
export function MasterProjects() {
  const custs = useLoad<any>("/master/customers");
  const [cid, setCid] = useState("");
  const projs = useLoad<any>(cid ? `master/projects?customer_id=${cid}`
    : null);
  const [form, setForm] = useState({ project_id: "", customer_id: "",
    name: "" });
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="项目库"
        desc="项目关联客户、SKU 范围与预算；按客户作用域访问" />
      <div className="card">
        <h3>新建项目</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input placeholder="project_id" aria-label="项目ID"
            value={form.project_id}
            onChange={(e) => setForm({ ...form,
              project_id: e.target.value })} />
          <input placeholder="customer_id" aria-label="所属客户"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form,
              customer_id: e.target.value })} />
          <input placeholder="名称" aria-label="项目名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("master/projects", form);
              setMsg("创建成功"); projs.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>创建</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      <div className="card">
        <h3>按客户查看</h3>
        <select value={cid} aria-label="选择客户"
          onChange={(e) => setCid(e.target.value)}>
          <option value="">选择客户…</option>
          {(custs.data?.customers ?? []).map((cu: any) => (
            <option key={cu.customer_id} value={cu.customer_id}>
              {cu.name}（{cu.customer_id}）</option>
          ))}
        </select>
        {custs.err && <ErrorState message={custs.err}
          onRetry={custs.reload} />}
        {projs.err && <ErrorState message={projs.err}
          onRetry={projs.reload} />}
        {projs.data && (projs.data.projects.length === 0
          ? <EmptyState title="该客户暂无项目" />
          : (
            <table className="table">
              <thead><tr><th>project_id</th><th>名称</th><th>状态</th>
                </tr></thead>
              <tbody>
                {projs.data.projects.map((p: any) => (
                  <tr key={p.project_id}>
                    <td data-label="project_id">{p.project_id}</td>
                    <td data-label="名称">{p.name}</td>
                    <td data-label="状态">{p.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
      </div>
    </>
  );
}

// ---- SKU 库 ----
export function MasterSkus() {
  const skus = useLoad<any>("/master/skus?include_superseded=true");
  const [form, setForm] = useState({ sku_id: "", canonical_name: "",
    brand: "", category: "", volume: "", barcode: "",
    package_version: "v1", valid_from: "", valid_to: "" });
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="SKU 库"
        desc="共享主数据：别名 / 客户显示名 / 有效期 / 新旧包装 supersede 链" />
      <div className="card">
        <h3>新建 SKU</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input placeholder="sku_id" aria-label="SKU ID"
            value={form.sku_id}
            onChange={(e) => setForm({ ...form, sku_id: e.target.value })} />
          <input placeholder="canonical_name" aria-label="规范名"
            value={form.canonical_name}
            onChange={(e) => setForm({ ...form,
              canonical_name: e.target.value })} />
          <input placeholder="品牌" aria-label="品牌" value={form.brand}
            onChange={(e) => setForm({ ...form, brand: e.target.value })} />
          <input placeholder="容量" aria-label="容量" value={form.volume}
            onChange={(e) => setForm({ ...form, volume: e.target.value })} />
          <input placeholder="条码" aria-label="条码" value={form.barcode}
            onChange={(e) => setForm({ ...form, barcode: e.target.value })} />
          <input placeholder="包装版本 v1/v2" aria-label="包装版本"
            value={form.package_version}
            onChange={(e) => setForm({ ...form,
              package_version: e.target.value })} />
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("master/skus", form);
              setMsg("创建成功"); skus.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>创建</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {skus.err && <ErrorState message={skus.err} onRetry={skus.reload} />}
      {!skus.data && !skus.err && <Loading />}
      {skus.data && (skus.data.skus.length === 0
        ? <EmptyState title="暂无 SKU" />
        : (
          <table className="table">
            <thead><tr><th>sku_id</th><th>规范名</th><th>包装</th>
              <th>有效期</th><th>状态</th><th>别名/显示名</th></tr></thead>
            <tbody>
              {skus.data.skus.map((s: any) => (
                <tr key={s.sku_id}>
                  <td data-label="sku_id">{s.sku_id}</td>
                  <td data-label="规范名">{s.canonical_name}</td>
                  <td data-label="包装">{s.package_version}
                    {s.superseded_by ? ` → ${s.superseded_by}` : ""}</td>
                  <td data-label="有效期" className="v">
                    {s.valid_from || "—"} ~ {s.valid_to || "长期"}</td>
                  <td data-label="状态">{s.status}</td>
                  <td data-label="别名" className="v"
                    style={{ fontSize: 11 }}>
                    {(s.aliases ?? []).map((a: any) =>
                      `${a.alias}（${a.kind === "customer_display_name"
                        ? `客户 ${a.customer_id}` : "别名"}）`)
                      .join("、") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </>
  );
}
