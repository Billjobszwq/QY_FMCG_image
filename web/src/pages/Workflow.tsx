import { useEffect, useState } from "react";
import ModuleTabs from "./ModuleTabs";

// 工作流：n8n 风格节点画布。节点=子系统步骤，边=数据/控制流，
// 状态色来自 Cycle 投影 + 服务健康。点击节点显示证据。
interface NodeDef { id: string; label: string; x: number; y: number;
  wf: string; }
const NODES: NodeDef[] = [
  { id: "ingest", label: "数据接入\n三批对账", x: 20, y: 40, wf: "data" },
  { id: "quality", label: "质量门禁\nqpol_n2_v1", x: 210, y: 40, wf: "data" },
  { id: "sam", label: "SAM 教师\nmask/box", x: 400, y: 40, wf: "data" },
  { id: "snap", label: "Snapshot v3\n四数据集冻结", x: 590, y: 40, wf: "data" },
  { id: "m1", label: "M1 检测器\npilot", x: 400, y: 190, wf: "train" },
  { id: "m2", label: "M2 分割\nstudent", x: 590, y: 190, wf: "train" },
  { id: "m3", label: "M3 分类\n长尾消融", x: 780, y: 190, wf: "train" },
  { id: "m4", label: "M4 Qwen\nQLoRA", x: 970, y: 190, wf: "train" },
  { id: "eval", label: "独立评估\nholdout v3", x: 780, y: 340, wf: "eval" },
  { id: "mg", label: "micro-gold\nLS22 人工", x: 590, y: 340, wf: "eval" },
  { id: "profile", label: "Profile\n候选门禁", x: 400, y: 340, wf: "serve" },
  { id: "prod", label: "production\nlegacy 服务", x: 210, y: 340, wf: "serve" },
];
const EDGES: [string, string][] = [
  ["ingest", "quality"], ["quality", "sam"], ["sam", "snap"],
  ["snap", "m1"], ["snap", "m2"], ["snap", "m3"], ["snap", "m4"],
  ["m3", "eval"], ["m4", "eval"], ["eval", "mg"], ["mg", "profile"],
  ["profile", "prod"],
];

export default function Workflow() {
  const [cycle, setCycle] = useState<any>(null);
  const [sel, setSel] = useState<NodeDef | null>(null);
  useEffect(() => {
    fetch("/api/v1/training/cycle").then((r) => r.json())
      .then(setCycle).catch(() => {});
  }, []);
  const nodeState = (id: string): string => {
    const map: Record<string, string> = {
      ingest: "done", quality: "done", sam: "done", snap: "done",
      m1: "done", m2: "done", m3: "done", m4: "done",
      eval: "done", mg: "running", profile: "waiting", prod: "done",
    };
    return map[id] ?? "todo";
  };
  const color = (st: string) =>
    st === "done" ? "var(--green)" :
    st === "running" ? "var(--blue)" :
    st === "waiting" ? "var(--amber)" : "var(--lavender)";
  const pos = (id: string) => NODES.find((n) => n.id === id)!;
  return (
    <div>
      <span className="kicker">06 · 工作流 · workflow-agent</span>
      <ModuleTabs active="/workflow" items={[{ to: "/workflow", label: "流水线画布" }, { to: "/runs", label: "Graph Runs" }, { to: "/taskboard", label: "任务板" }]} />
      <h1>工作流</h1>
      <p className="muted">
        Agent 编排的端到端流水线 · 数据 → 训练 → 评估 → 人工金标准 → 服务
      </p>
      <div className="wf-canvas" style={{ position: "relative",
        height: 480, minWidth: 1180 }}>
        <svg width={1180} height={480} style={{ position: "absolute",
          inset: 0 }}>
          {EDGES.map(([a, b], i) => {
            const pa = pos(a); const pb = pos(b);
            return (
              <line key={i} x1={pa.x + 170} y1={pa.y + 30}
                x2={pb.x} y2={pb.y + 30} stroke="#000" strokeWidth={2}
                strokeDasharray={nodeState(b) === "todo" ? "6 4" : ""} />
            );
          })}
        </svg>
        {NODES.map((n) => (
          <div key={n.id} className="wf-node"
            style={{ left: n.x, top: n.y, background: color(nodeState(n.id)) }}
            onClick={() => setSel(n)}>
            {n.label.split("\n")[0]}
            <span className="st">{n.label.split("\n")[1]} ·
              {nodeState(n.id)}</span>
          </div>
        ))}
      </div>
      {sel && (
        <div className="card-lg tint-lavender" style={{ marginTop: 20 }}>
          <h3>{sel.label.replace("\n", " · ")}</h3>
          <p>
            状态：{nodeState(sel.id)} ·
            Cycle：{cycle?.status ?? "—"} ·
            证据见任务板与评估报告。
          </p>
        </div>
      )}
    </div>
  );
}
