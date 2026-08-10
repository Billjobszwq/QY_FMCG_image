import { useEffect, useState } from "react";
import { HealthBody } from "../api";

// 总览：units 拼贴 —— 超大标题 + 非对称色块 + 货架图 + 黑条 CTA。
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
    /CANDIDATE|REJECTED/.test(a.candidate_status ?? ""));
  return (
    <div>
      <span className="kicker">01 · 总览</span>
      <div className="display">
        不止是识别。<br />一种看货架的新方式。
      </div>
      <div className="collage">
        <div className="blk c-red span5">
          <h2>当前 Gate</h2>
          <p style={{ fontWeight: 700 }}>{gate?.gate ?? "—"}</p>
          <p>机器侧数据 / 训练 / 评估 / 门禁已全部闭环；
            等待唯一的人工动作。</p>
        </div>
        <div className="blk img span4">
          <img src="img/shelf1.jpg" alt="货架实景" />
        </div>
        <div className="blk c-green span3">
          <h2>Cycle</h2>
          <div className="big">{cycle?.summary?.done ?? 0}/19</div>
          <p>节点完成 · 剩余评估与决策</p>
        </div>
        <div className="blk c-violet span7">
          <h2>下一步只有一件事</h2>
          <p>进入标注中心 → LS 项目 22 → 完成 200 条真实人工审核。
            一致后升级 human_final，候选模型解禁。</p>
          <a className="cta-bar" style={{ margin: 0 }} href="#/labelstudio">
            进入标注中心 <span className="arrow">→</span>
          </a>
        </div>
        <div className="blk c-yellow span5">
          <h2>micro-gold</h2>
          <div className="big">200</div>
          <p>条待人工 · LS 项目 22 · 唯一有效入口 · 项目 21 已失效</p>
        </div>
        <div className="blk img span4">
          <img src="img/shelf2.jpg" alt="货架实景 2" />
        </div>
        <div className="blk c-blue span4">
          <h2>候选模型</h2>
          <div className="big">{cands.length}</div>
          <p>待 micro-gold 解禁 · M4 独立评估无收益已如实记录</p>
        </div>
        <div className="blk c-orange span4">
          <h2>production</h2>
          <p style={{ fontWeight: 800 }}>prod_20260805_v5_r1</p>
          <p>未切换 · 人工批准制 · 非 SaaS</p>
        </div>
        <div className="blk c-lav span4">
          <h2>服务</h2>
          <div className="big" style={{ fontSize: 34 }}>
            {health?.status ?? "—"}
          </div>
          <p>8091 识别 · 8300 标注 · 8400 工作台 · 8455 LLM</p>
        </div>
      </div>
      <a className="cta-bar" href="#/workflow">
        看整条工作流：数据 → SAM → 训练 → 评估 → 人工金标准 → 服务
        <span className="arrow">→</span>
      </a>
      <div className="blk c-white span12" style={{ minHeight: 0 }}>
        <h2>候选模型状态</h2>
        <table>
          <thead><tr><th>模型</th><th>状态</th><th>blocker</th></tr></thead>
          <tbody>
            {(arts?.artifacts ?? []).map((a: any) => (
              <tr key={a.artifact_id}>
                <td style={{ fontWeight: 700 }}>{a.artifact_id}</td>
                <td><span className="pill on-blue">{a.candidate_status}</span></td>
                <td style={{ maxWidth: 460 }}>{a.blocker}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
