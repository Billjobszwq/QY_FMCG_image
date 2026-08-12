// ABOS T2/T5：Agentic Business OS 工作台壳层。
// 一级导航来自 Module Registry 投影（不硬编码）；二级路由由
// ModuleUIRegistry（platform/ui_registry.tsx）统一驱动（Z-1/P1-003）；
// 旧路由保留 redirect；身份/production 全部来自实时 API。
import { useEffect, lazy, Suspense, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from
  "react-router-dom";
import "./platform/design/tokens.css";
import "./platform/design/shell.css";
import "./styles.css";
import {
  AuthMe, HealthBody, fetchHealth, fetchMe, login, logout,
} from "./api";
import {
  ModuleView, PlatformIdentity, ProductionInfo, STATUS_CN,
  accentVar, fetchIdentity, fetchModules, fetchProduction,
} from "./platform/registry";
import SupervisorWorkspace from "./platform/SupervisorWorkspace";
import { MODULE_REDIRECTS, MODULE_ROUTES } from "./platform/ui_registry";
// SI2 T9：三级深链页同样路由级 lazy（不进首页初始包）
const NewPackaging = lazy(() => import("./pages/NewPackaging"));
const CascadeTasks = lazy(() => import("./pages/CascadeTasks"));

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
  // ABOSV3 T11：系统管理仅管理员可见；reference.echo 不进导航
  const navModules = modules.filter((m) => {
    if (m.module_id === "reference.echo") return false;
    if (m.module_id === "system" && me.role !== "admin") return false;
    return true;
  });

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
            <Route path="/" element={<Navigate to="/home" replace />} />
            {/* ABOSV2 Z-1：模块路由由 ModuleUIRegistry 统一驱动 */}
            {Object.entries(MODULE_ROUTES).map(([path, factory]) => (
              <Route key={path} path={path}
                element={factory({ health, modules, identity })} />
            ))}
            {Object.entries(MODULE_REDIRECTS).map(([from, to]) => (
              <Route key={from} path={from}
                element={<Navigate to={to} replace />} />
            ))}
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
            <Route path="/biz" element={<Navigate to="/analytics/reports"
              replace />} />
            <Route path="/biz/*" element={<Navigate
              to="/analytics/reports" replace />} />
            <Route path="/analytics/bi" element={<Navigate
              to="/analytics/reports" replace />} />
            <Route path="/taskboard" element={<Navigate to="/home"
              replace />} />
            <Route path="/runs" element={<Navigate to="/workflow/runs"
              replace />} />
            {/* 专业子页保留深链接（三级内容） */}
            <Route path="/vision/cascade" element={
              <Suspense fallback={<p className="muted">加载中…</p>}>
                <CascadeTasks /></Suspense>} />
            <Route path="/vision/packaging" element={
              <Suspense fallback={<p className="muted">加载中…</p>}>
                <NewPackaging /></Suspense>} />
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
