import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { fetchHealth, HealthBody } from "./api";
import Overview from "./pages/Overview";
import GraphRuns from "./pages/GraphRuns";
import Recognition from "./pages/Recognition";
import Annotation from "./pages/Annotation";
import Assets from "./pages/Assets";
import Training from "./pages/Training";
import SystemStatus from "./pages/SystemStatus";

const NAV = [
  { to: "/", label: "系统总览" },
  { to: "/runs", label: "Graph Runs" },
  { to: "/recognition", label: "图片识别" },
  { to: "/annotation", label: "标注审核" },
  { to: "/assets", label: "数据资产" },
  { to: "/training", label: "训练模型" },
  { to: "/status", label: "系统状态" },
];

export default function App() {
  const [health, setHealth] = useState<HealthBody | null>(null);

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

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◈</span> 统一工作台
          <span className="sub">Platform V2 · 8400</span>
        </div>
        <div className={`overall overall-${overall ?? "unknown"}`}>
          {overall ? `平台状态：${overall}` : "平台状态：加载中…"}
        </div>
      </header>
      {overall === "degraded" && (
        <div className="banner banner-degraded">
          部分依赖服务不可用（如 Label Studio / ML Backend），平台以 degraded 模式继续服务。
        </div>
      )}
      {overall === "unavailable" && (
        <div className="banner banner-unavailable">关键服务不可用：识别服务（8091）未连接。</div>
      )}
      <div className="body">
        <nav className="sidenav">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) => (isActive ? "nav active" : "nav")}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <main className="content">
          <Routes>
            <Route path="/" element={<Overview health={health} />} />
            <Route path="/runs" element={<GraphRuns />} />
            <Route path="/recognition" element={<Recognition />} />
            <Route path="/annotation" element={<Annotation health={health} />} />
            <Route path="/assets" element={<Assets />} />
            <Route path="/training" element={<Training />} />
            <Route path="/status" element={<SystemStatus health={health} />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
