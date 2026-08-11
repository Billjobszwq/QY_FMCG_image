// ABOS T2/T5：Agentic Business OS 工作台壳层。
// 一级导航来自 Module Registry 投影（不硬编码）；二级为真实 route；
// 旧路由保留 redirect；身份/production 全部来自实时 API。
import { useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from
  "react-router-dom";
import "./platform/design/tokens.css";
import "./platform/design/shell.css";
import "./styles.css";
import {
  AuthMe, HealthBody, fetchAgents, fetchHealth, fetchMe, login, logout,
} from "./api";
import {
  ModuleView, PlatformIdentity, ProductionInfo, STATUS_CN,
  accentVar, fetchIdentity, fetchModules, fetchProduction,
} from "./platform/registry";
import SupervisorWorkspace from "./platform/SupervisorWorkspace";
import Home from "./pages/Home";
import GraphRuns from "./pages/GraphRuns";
import {
  WorkflowAgentsAndModels, WorkflowApprovals, WorkflowConnectors,
  WorkflowEvidenceUsage, WorkflowRunCenter, WorkflowStudio,
  WorkflowTemplates,
} from "./pages/Workflow";
import SystemStatus from "./pages/SystemStatus";
import {
  IamAccounts, IamAudit, MasterCustomers, MasterProjects, MasterSkus,
} from "./pages/IamMaster";
import { SurveyDesign, SurveyField, SurveyReport } from "./pages/Survey";
import {
  AnalyticsAnomalies, AnalyticsReports, AnalyticsSemantics,
} from "./pages/Analytics";
import { GeoAddresses, GeoField, GeoVisit } from "./pages/Geo";
import { FinanceContracts, FinanceInvoices } from "./pages/Finance";
import {
  RecognizeNow, VisionAnnotation, VisionDatasets, VisionEvidence,
  VisionModels, VisionTasks,
} from "./pages/Vision";
import NewPackaging from "./pages/NewPackaging";
import CascadeTasks from "./pages/CascadeTasks";

// ---- 工作流 / Agent 矩阵（二级：/workflow/agents） ----
function AgentsMatrix({ modules }: { modules: ModuleView[] }) {
  const [agents, setAgents] = useState<any[] | null>(null);
  useEffect(() => {
    fetchAgents().then((d) => setAgents(d.agents as any[])).catch(
      () => setAgents([]));
  }, []);
  const byId = useMemo(() => {
    const m: Record<string, string> = {};
    for (const mod of modules) {
      for (const a of mod.agents) m[a] = mod.name;
    }
    return m;
  }, [modules]);
  return (
    <div className="page">
      <div className="page-header"><h1>Agent 矩阵</h1>
        <span className="desc">AgentManifest 注册、权限范围与所属模块</span>
      </div>
      <div className="card">
        {agents === null ? <p className="muted">加载中…</p> : (
          <table className="table">
            <thead><tr><th>Agent</th><th>域</th><th>风险</th>
              <th>所属模块</th></tr></thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.agent_id}>
                  <td className="k">{a.agent_id}</td>
                  <td>{a.domain}</td>
                  <td>{a.risk_level}</td>
                  <td>{byId[a.agent_id] ?? "平台"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---- reference.echo：非识别模块证明内核通用 ----
function ReferenceEcho() {
  const [out, setOut] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/v1/reference/echo?text=hello-from-workbench")
      .then((r) => r.json()).then((d) => setOut(JSON.stringify(d, null, 2)))
      .catch((e) => setOut(String(e)));
  }, []);
  return (
    <div className="page">
      <div className="page-header"><h1>参考模块 Echo</h1>
        <span className="desc">最小非业务 Domain Pack：注册即可发现/调用</span>
      </div>
      <div className="card">
        <h3>GET /api/v1/reference/echo</h3>
        <pre>{out ?? "调用中…"}</pre>
      </div>
    </div>
  );
}

function ModulePage(_props: { modules: ModuleView[]; moduleId: string }) {
  // ABOSV2 Phase A–F：所有 planned 插槽已被真实路由取代；
  // 保留组件签名供未来 planned 模块复用（不再被路由引用）。
  return null;
}
void ModulePage;

export default function App() {
  const location = useLocation();
  const [health, setHealth] = useState<HealthBody | null>(null);
  const [me, setMe] = useState<AuthMe | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [modules, setModules] = useState<ModuleView[]>([]);
  const [identity, setIdentity] = useState<PlatformIdentity | null>(null);
  const [prod, setProd] = useState<ProductionInfo | null>(null);

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null))
      .finally(() => setAuthChecked(true));
    fetchIdentity().then(setIdentity).catch(() => {});
    fetchProduction().then(setProd).catch(() => {});
    fetchModules().then(setModules).catch(() => {});
  }, []);
  useEffect(() => {
    let stop = false;
    const load = () => {
      if (document.visibilityState !== "visible") return; // 后台降频
      fetchHealth().then((h) => !stop && setHealth(h))
        .catch(() => !stop && setHealth(null));
    };
    load();
    const t = setInterval(load, 20000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  const onLogin = async () => {
    setLoginBusy(true); setLoginError(null);
    try { setMe(await login(username, password)); setPassword(""); }
    catch (e) { setLoginError(e instanceof Error ? e.message : String(e)); }
    finally { setLoginBusy(false); }
  };

  if (!authChecked) {
    return <div className="login-wrap"><p className="muted">加载中…</p></div>;
  }

  if (!me) {
    return (
      <div className="login-wrap">
        <div className="login-card">
          <span className="login-brand">
            {identity?.product_name ?? "Agentic Business OS"}</span>
          <h1 className="login-title">进入工作台</h1>
          <p className="login-sub">
            {identity?.definition ?? "Graph+Loop 驱动的智能业务操作系统"}
          </p>
          <input placeholder="用户名" aria-label="用户名" value={username}
            onChange={(e) => setUsername(e.target.value)} />
          <input placeholder="口令" aria-label="口令" type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onLogin()} />
          {loginError && <div className="banner banner-error">
            {loginError}</div>}
          <button className="btn primary" disabled={loginBusy}
            onClick={onLogin}>{loginBusy ? "登录中…" : "进入"}</button>
        </div>
      </div>
    );
  }

  // 当前模块：按导航 route 前缀匹配（一级 active 唯一）
  const currentModule = modules.find((m) =>
    location.pathname === m.primary_route
    || m.navigation.some((n) => location.pathname === n.route
      || (n.route !== m.primary_route
        && location.pathname.startsWith(n.route + "/"))));
  const navModules = modules.filter((m) => m.module_id !== "reference.echo");

  return (
    <div className="abos-app">
      <header className="topbar">
        <span className="topbar-brand">
          {identity?.short ?? "qy·abos"} · {identity?.product_name_zh ??
            "智能业务操作系统"}</span>
        <span className="topbar-env">
          {identity?.environment ?? "local"} · {me.actor}</span>
        <span className="topbar-spacer" />
        <span className="topbar-prod">
          production：{prod?.found ? (prod.bundle_id ?? "未知") : "未加载"}
        </span>
        <button className="btn small"
          onClick={async () => { await logout(); setMe(null); }}>退出</button>
      </header>
      <div className="shell-body">
        <nav className="pnav" aria-label="一级模块导航">
          {navModules.map((m) => (
            <NavLink key={m.module_id}
              to={m.navigation[0]?.route ?? m.primary_route}
              title={m.name}
              aria-label={`${m.name}（${STATUS_CN[m.status] ?? m.status}）`}
              className={({ isActive }) => (isActive
                || (currentModule?.module_id === m.module_id)
                ? "pnav-item active" : "pnav-item")}>
              <span className="pnav-dot"
                style={{ background: accentVar(m.theme_token) }} />
              <span className="label">{m.name}</span>
              <span className={`pnav-status ${m.status}`}>
                {STATUS_CN[m.status] ?? m.status}</span>
            </NavLink>
          ))}
        </nav>
        <div className="main-col">
          {currentModule && currentModule.navigation.length > 0 && (
            <nav className="snav" aria-label="二级功能导航">
              {currentModule.navigation.map((n) => (
                <NavLink key={n.route} to={n.route}
                  className={({ isActive }) => isActive ? "active" : ""}>
                  {n.label}</NavLink>
              ))}
            </nav>
          )}
          <Routes>
            <Route path="/" element={<Home health={health}
              modules={modules} identity={identity} />} />
            <Route path="/home" element={<Home health={health}
              modules={modules} identity={identity} />} />
            {/* 智能识别域：六条真实二级路由 */}
            <Route path="/vision" element={<Navigate to="/vision/recognize"
              replace />} />
            <Route path="/vision/recognize"
              element={<div className="page wide">
                <RecognizeNow health={health} /></div>} />
            <Route path="/vision/tasks"
              element={<div className="page wide"><VisionTasks /></div>} />
            <Route path="/vision/annotation"
              element={<div className="page wide">
                <VisionAnnotation health={health} /></div>} />
            <Route path="/vision/datasets"
              element={<div className="page wide"><VisionDatasets /></div>} />
            <Route path="/vision/models"
              element={<div className="page wide"><VisionModels /></div>} />
            <Route path="/vision/evidence"
              element={<div className="page wide"><VisionEvidence /></div>} />
            {/* 数据与资产 */}
            <Route path="/data/assets"
              element={<div className="page wide">
                <VisionDatasets /></div>} />
            <Route path="/data/quality"
              element={<div className="page wide"><VisionEvidence /></div>} />
            {/* 工作流与 Agent（ABOSV2 Phase C：Studio 七页签） */}
            <Route path="/workflow" element={<Navigate to="/workflow/studio"
              replace />} />
            <Route path="/workflow/studio"
              element={<div className="page wide"><WorkflowStudio /></div>} />
            <Route path="/workflow/templates"
              element={<div className="page wide">
                <WorkflowTemplates /></div>} />
            <Route path="/workflow/runs"
              element={<div className="page wide">
                <WorkflowRunCenter /><GraphRuns /></div>} />
            <Route path="/workflow/approvals"
              element={<div className="page wide">
                <WorkflowApprovals /></div>} />
            <Route path="/workflow/connectors"
              element={<div className="page wide">
                <WorkflowConnectors /></div>} />
            <Route path="/workflow/agents"
              element={<div className="page wide">
                <WorkflowAgentsAndModels />
                <AgentsMatrix modules={modules} /></div>} />
            <Route path="/workflow/evidence"
              element={<div className="page wide">
                <WorkflowEvidenceUsage /></div>} />
            {/* 账号与权限 / 客户与主数据（ABOSV2 Phase D） */}
            <Route path="/iam" element={<Navigate to="/iam/accounts"
              replace />} />
            <Route path="/iam/accounts"
              element={<div className="page wide"><IamAccounts /></div>} />
            <Route path="/iam/audit"
              element={<div className="page wide"><IamAudit /></div>} />
            <Route path="/master" element={<Navigate
              to="/master/customers" replace />} />
            <Route path="/master/customers"
              element={<div className="page wide">
                <MasterCustomers /></div>} />
            <Route path="/master/projects"
              element={<div className="page wide">
                <MasterProjects /></div>} />
            <Route path="/master/skus"
              element={<div className="page wide"><MasterSkus /></div>} />
            {/* 调研与问卷（ABOSV2 Phase E，真实后端） */}
            <Route path="/survey" element={<Navigate to="/survey/design"
              replace />} />
            <Route path="/survey/design"
              element={<div className="page wide">
                <SurveyDesign /></div>} />
            <Route path="/survey/field"
              element={<div className="page wide"><SurveyField /></div>} />
            <Route path="/survey/report"
              element={<div className="page wide">
                <SurveyReport /></div>} />
            {/* 分析与 BI（ABOSV2 Phase F，真实后端） */}
            <Route path="/analytics" element={<Navigate
              to="/analytics/reports" replace />} />
            <Route path="/analytics/reports"
              element={<div className="page wide">
                <AnalyticsReports /></div>} />
            <Route path="/analytics/anomalies"
              element={<div className="page wide">
                <AnalyticsAnomalies /></div>} />
            <Route path="/analytics/semantics"
              element={<div className="page wide">
                <AnalyticsSemantics /></div>} />
            {/* 位置与外勤（ABOSV2 Phase F，真实后端） */}
            <Route path="/geo" element={<Navigate to="/geo/addresses"
              replace />} />
            <Route path="/geo/addresses"
              element={<div className="page wide">
                <GeoAddresses /></div>} />
            <Route path="/geo/field"
              element={<div className="page wide"><GeoField /></div>} />
            <Route path="/geo/visit"
              element={<div className="page wide"><GeoVisit /></div>} />
            {/* 财务与结算（ABOSV2 Phase F，真实后端） */}
            <Route path="/finance" element={<Navigate
              to="/finance/contracts" replace />} />
            <Route path="/finance/contracts"
              element={<div className="page wide">
                <FinanceContracts /></div>} />
            <Route path="/finance/invoices"
              element={<div className="page wide">
                <FinanceInvoices /></div>} />
            {/* 系统与开发者 */}
            <Route path="/status"
              element={<SystemStatus health={health} />} />
            {/* planned 模块插槽已全部被真实路由取代（ABOSV2 Phase A–F） */}
            <Route path="/reference/echo" element={<ReferenceEcho />} />
            {/* 兼容旧路由（redirect，deprecated） */}
            <Route path="/recognition" element={<Navigate
              to="/vision/recognize" replace />} />
            <Route path="/cascade" element={<Navigate to="/vision/tasks"
              replace />} />
            <Route path="/labelstudio" element={<Navigate
              to="/vision/annotation" replace />} />
            <Route path="/annotation" element={<Navigate
              to="/vision/annotation" replace />} />
            <Route path="/assets" element={<Navigate to="/data/assets"
              replace />} />
            <Route path="/training" element={<Navigate to="/vision/models"
              replace />} />
            <Route path="/models-runtime" element={<Navigate
              to="/vision/models" replace />} />
            <Route path="/packaging" element={<Navigate
              to="/vision/datasets" replace />} />
            <Route path="/biz" element={<Navigate to="/analytics/bi"
              replace />} />
            <Route path="/biz/*" element={<Navigate to="/analytics/bi"
              replace />} />
            <Route path="/taskboard" element={<Navigate to="/home"
              replace />} />
            <Route path="/runs" element={<Navigate to="/workflow/runs"
              replace />} />
            {/* 专业子页保留深链接（三级内容） */}
            <Route path="/vision/cascade" element={<CascadeTasks />} />
            <Route path="/vision/packaging" element={<NewPackaging />} />
            <Route path="*" element={<div className="page">
              <div className="state-view">
                <div className="title">页面不存在</div>
                <div className="next">请从左侧模块导航进入，
                  或回到 <NavLink to="/">主管工作台</NavLink></div>
              </div></div>} />
          </Routes>
          <footer style={{ padding: "14px 24px", fontSize: 12,
            color: "var(--text-muted)",
            borderTop: "1px solid var(--border)" }}>
            {identity?.product_name ?? "Agentic Business OS"} ·
            Graph+Loop 驱动 · 识别为首个 Domain Pack ·
            production={prod?.found ? (prod.bundle_id ?? "未知") : "—"}
            （实时读取，人工批准制）
          </footer>
        </div>
        <SupervisorWorkspace />
      </div>
    </div>
  );
}
