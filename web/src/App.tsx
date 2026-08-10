import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { AuthMe, fetchHealth, fetchMe, HealthBody, login, logout } from "./api";
import Overview from "./pages/Overview";
import GraphRuns from "./pages/GraphRuns";
import Recognition from "./pages/Recognition";
import Annotation from "./pages/Annotation";
import Assets from "./pages/Assets";
import Training from "./pages/Training";
import SystemStatus from "./pages/SystemStatus";
import CascadeTasks from "./pages/CascadeTasks";
import ModelRuntime from "./pages/ModelRuntime";
import NewPackaging from "./pages/NewPackaging";
import AgentChat from "./pages/AgentChat";
import TaskBoard from "./pages/TaskBoard";
import Workflow from "./pages/Workflow";
import LabelStudioHub from "./pages/LabelStudioHub";

const NAV = [
  { to: "/", label: "总览" },
  { to: "/taskboard", label: "任务板" },
  { to: "/workflow", label: "工作流" },
  { to: "/recognition", label: "识别" },
  { to: "/labelstudio", label: "标注中心" },
  { to: "/annotation", label: "审核" },
  { to: "/assets", label: "数据" },
  { to: "/training", label: "训练" },
  { to: "/cascade", label: "级联" },
  { to: "/models-runtime", label: "模型" },
  { to: "/packaging", label: "新包装" },
  { to: "/runs", label: "Graph" },
  { to: "/status", label: "状态" },
];

export default function App() {
  const [health, setHealth] = useState<HealthBody | null>(null);
  const [me, setMe] = useState<AuthMe | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);

  useEffect(() => {
    fetchMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setAuthChecked(true));
  }, []);

  const onLogin = async () => {
    setLoginBusy(true);
    setLoginError(null);
    try {
      setMe(await login(username, password));
      setPassword("");
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoginBusy(false);
    }
  };

  const onLogout = async () => {
    await logout();
    setMe(null);
  };

  useEffect(() => {
    let stop = false;
    const load = () =>
      fetchHealth()
        .then((h) => !stop && setHealth(h))
        .catch(() => !stop && setHealth(null));
    load();
    const t = setInterval(load, 15000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, []);

  const overall = health?.status;

  if (!authChecked) return <div className="main">加载中…</div>;

  if (!me) {
    return (
      <div className="main" style={{ maxWidth: 460, margin: "8vh auto" }}>
        <h1>统一工作台</h1>
        <p className="muted">Agent + Workflow 驱动的 SKU 识别系统</p>
        <div className="card-lg">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <input placeholder="用户名" value={username}
              onChange={(e) => setUsername(e.target.value)} />
            <input placeholder="口令" type="password" value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onLogin()} />
            {loginError && <span className="pill err">{loginError}</span>}
            <button className="btn violet" disabled={loginBusy} onClick={onLogin}>
              进入工作台
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="topbar">
        <span className="brand">◆ 统一工作台</span>
        <span className={
          overall === "healthy" ? "pill ok" :
          overall === "degraded" ? "pill warn" : "pill err"}>
          {overall === "healthy" ? "● 全部服务在线" :
           overall === "degraded" ? "● 部分降级" : "● 异常"}
        </span>
        <span className="pill muted">Gate 见总览</span>
        <span style={{ flex: 1 }} />
        <span className="pill info">{me.actor}</span>
        <button className="btn ghost" style={{ padding: "8px 16px" }}
          onClick={onLogout}>退出</button>
      </div>
      <div className="shell">
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <main className="main">
          <Routes>
            <Route path="/" element={<Overview health={health} />} />
            <Route path="/taskboard" element={<TaskBoard />} />
            <Route path="/workflow" element={<Workflow />} />
            <Route path="/runs" element={<GraphRuns />} />
            <Route path="/recognition" element={<Recognition />} />
            <Route path="/labelstudio" element={<LabelStudioHub />} />
            <Route path="/annotation" element={<Annotation health={health} />} />
            <Route path="/assets" element={<Assets />} />
            <Route path="/training" element={<Training />} />
            <Route path="/cascade" element={<CascadeTasks />} />
            <Route path="/models-runtime" element={<ModelRuntime />} />
            <Route path="/packaging" element={<NewPackaging />} />
            <Route path="/status" element={<SystemStatus health={health} />} />
          </Routes>
        </main>
      </div>
      <AgentChat />
    </div>
  );
}
