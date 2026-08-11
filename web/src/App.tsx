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
import BizIntel from "./pages/BizIntel";

// 一级模块：一模块一色系一 Agent；二级功能见各页 ModuleTabs；三级操作在页内。
const RAIL = [
  { to: "/", label: "总览·主管", c: "var(--violet)" },
  { to: "/recognition", label: "图像识别", c: "var(--blue)" },
  { to: "/labelstudio", label: "标注中心", c: "var(--green)" },
  { to: "/assets", label: "数据仓库", c: "var(--yellow)" },
  { to: "/training", label: "模型训练", c: "var(--orange)" },
  { to: "/workflow", label: "工作流", c: "var(--lavender)" },
  { to: "/biz", label: "经营智能", c: "var(--red)" },
  { to: "/status", label: "系统", c: "var(--green)" },
];


export default function App() {
  const [health, setHealth] = useState<HealthBody | null>(null);
  const [me, setMe] = useState<AuthMe | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [gate, setGate] = useState<string>("");

  useEffect(() => {
    fetchMe().then(setMe).catch(() => setMe(null))
      .finally(() => setAuthChecked(true));
  }, []);
  useEffect(() => {
    fetch("/api/v1/platform/gate").then((r) => r.json())
      .then((d) => setGate(d.gate ?? "")).catch(() => {});
  }, []);
  useEffect(() => {
    let stop = false;
    const load = () => fetchHealth().then((h) => !stop && setHealth(h))
      .catch(() => !stop && setHealth(null));
    load();
    const t = setInterval(load, 15000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  const onLogin = async () => {
    setLoginBusy(true); setLoginError(null);
    try { setMe(await login(username, password)); setPassword(""); }
    catch (e) { setLoginError(e instanceof Error ? e.message : String(e)); }
    finally { setLoginBusy(false); }
  };

  if (!authChecked) return <div className="main">…</div>;
  if (!me) {
    return (
      <div className="main" style={{ maxWidth: 520, margin: "10vh auto" }}>
        <span className="kicker">qy · sku recognition</span>
        <div className="display">进入工作台。</div>
        <div className="blk c-white" style={{ minHeight: 0 }}>
          <input placeholder="用户名" value={username}
            onChange={(e) => setUsername(e.target.value)} />
          <input placeholder="口令" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onLogin()} />
          {loginError && <span className="pill on-red">{loginError}</span>}
          <button className="btn" disabled={loginBusy} onClick={onLogin}>
            进入 →
          </button>
        </div>
      </div>
    );
  }

  const mq = ` micro-gold 200 条待人工审核 ✦ Gate：${gate || "—"} ✦ ` +
    `production 未切换 ✦ 服务：${health?.status ?? "—"} ✦` +
    " 候选模型待 micro-gold 解禁 ✦ Agent + Workflow 驱动 ✦";

  return (
    <div>
      <div className="marquee"><div>{mq}{mq}</div></div>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", padding: "14px 40px 0 100px" }}>
        <span style={{ fontWeight: 900, fontFamily: "var(--font-display)",
          fontSize: 20 }}>qy·sku.</span>
        <span style={{ display: "flex", gap: 8 }}>
          <span className="pill on-blue">{me.actor}</span>
          <button className="btn black" style={{ padding: "8px 18px" }}
            onClick={async () => { await logout(); setMe(null); }}>
            退出
          </button>
        </span>
      </div>
      <div className="layout">
        <nav className="rail">
          {RAIL.map((n, i) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              style={{ background: n.c }}
              className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="top">
                <span>0{i + 1}</span><span>→</span>
              </span>
              <span>{n.label}</span>
            </NavLink>
          ))}

        </nav>
        <main className="content">
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
            <Route path="/biz" element={<BizIntel />} />
            <Route path="/biz/api" element={<BizIntel />} />
            <Route path="/biz/alert" element={<BizIntel />} />
            <Route path="/biz/cfg" element={<BizIntel />} />
            <Route path="/status" element={<SystemStatus health={health} />} />
          </Routes>
          <footer className="footer">
            <div className="logo">qy·sku.</div>
            <div className="fine">
              © 2026 QY · Agent + Workflow 驱动的 SKU 识别系统 ·
              非 SaaS · production=prod_20260805_v5_r1（人工批准制）
            </div>
          </footer>
        </main>
      </div>
      <AgentChat />
    </div>
  );
}
