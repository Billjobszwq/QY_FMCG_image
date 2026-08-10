import { useEffect, useState } from "react";
import { HealthBody } from "../api";

// 总览：units 风格拼贴。Gate + Cycle + micro-gold + 候选 + 服务。
export default function Overview({ health }: { health: HealthBody | null }) {
  const [gate, setGate] = useState<any>(null);
  const [cycle, setCycle] = useState<any>(null);
  const [arts, setArts] = useState<any>(null);
  useEffect(() => {
    fetch("/api/v1/platform/gate").then((r) => r.json()).then(setGate)
      .catch(() => {});
    fetch("/api/v1/training/cycle").then((r) => r.json()).then(setCycle)
      .catch(() => {});
    fetch("/api/v1/training/artifacts").then((r) => r.json()).then(setArts)
      .catch(() => {});
  }, []);
  const cands = (arts?.artifacts ?? []).filter((a: any) =>
    a.candidate_status?.includes("CANDIDATE") ||
    a.candidate_status?.includes("REJECTED"));
  return (
    <div>
      <h1>SKU 识别系统</h1>
      <p className="muted">Agent + Workflow 驱动 · 非 SaaS · 生产推进中</p>
      <div className="grid" style={{ marginBottom: 28 }}>
        <div className="tile" style={{ background: "var(--violet)",
          color: "#fff" }}>
          <span className="k">当前 Gate</span>
          <span style={{ fontWeight: 800, fontSize: 15 }}>
            {gate?.gate ?? "—"}
          </span>
        </div>
        <div className="tile" style={{ background: "var(--green)" }}>
          <span className="k">Cycle 进度</span>
          <span className="num">{cycle?.summary?.done ?? 0}/19</span>
          <span className="k">节点完成</span>
        </div>
        <div className="tile" style={{ background: "var(--card-yellow)" }}>
          <span className="k">micro-gold 待人工</span>
          <span className="num">200</span>
          <span className="k">LS 项目 22 · 唯一有效入口</span>
        </div>
        <div className="tile" style={{ background: "var(--blue)" }}>
          <span className="k">候选模型</span>
          <span className="num">{cands.length}</span>
          <span className="k">待 micro-gold 解禁</span>
        </div>
        <div className="tile" style={{ background: "var(--card-orange)" }}>
          <span className="k">production</span>
          <span style={{ fontWeight: 800 }}>prod_20260805_v5_r1</span>
          <span className="k">未切换 · 人工批准制</span>
        </div>
        <div className="tile" style={{ background: "var(--lavender)" }}>
          <span className="k">服务状态</span>
          <span style={{ fontWeight: 800, fontSize: 18 }}>
            {health?.status ?? "—"}
          </span>
          <span className="k">8091/8300/8400/8455</span>
        </div>
      </div>
      <div className="card-lg tint-coral">
        <h2>下一步只有一件事</h2>
        <p style={{ fontSize: 16 }}>
          进入标注中心 → LS 项目 22 → 完成 200 条真实人工审核。
          机器侧数据、训练、评估、门禁已全部闭环。
        </p>
        <a className="btn" style={{ background: "#fff", color: "#000" }}
          href="#/labelstudio">进入标注中心</a>
      </div>
      <div className="card-lg">
        <h3>候选模型状态</h3>
        <table>
          <thead><tr><th>模型</th><th>状态</th><th>blocker</th></tr></thead>
          <tbody>
            {(arts?.artifacts ?? []).map((a: any) => (
              <tr key={a.artifact_id}>
                <td>{a.artifact_id}</td>
                <td><span className="pill info">{a.candidate_status}</span></td>
                <td style={{ maxWidth: 420 }}>{a.blocker}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
