import { useEffect, useState } from "react";

// 任务板：units 风格卡片流。每卡只露标题/状态 pill/owner/更新时间，
// 详情（evidence/graph_run/acceptance）折叠。
const ORDER = ["todo", "running", "waiting", "review", "done"];
const CN: Record<string, string> = {
  todo: "待办", running: "运行中", waiting: "等待/阻塞",
  review: "待验收", done: "完成",
};
const TINT: Record<string, string> = {
  todo: "var(--card-yellow)", running: "var(--blue)",
  waiting: "var(--amber)", review: "var(--lavender)",
  done: "var(--green)",
};

export default function TaskBoard() {
  const [tb, setTb] = useState<Record<string, any[]>>({});
  useEffect(() => {
    const load = () =>
      fetch("/api/v1/taskboard").then((r) => r.json())
        .then((d) => setTb(d.states)).catch(() => {});
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);
  return (
    <div>
      <h1>任务板</h1>
      <p className="muted">Agent 与人工的共同工作队列 · 实时投影</p>
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        {ORDER.map((s) => (
          <div key={s} className="tcol">
            <span className="pill" style={{ background: TINT[s],
              marginBottom: 14 }}>
              {CN[s]}（{(tb[s] ?? []).length}）
            </span>
            {(tb[s] ?? []).map((c, i) => (
              <div key={i} className="tcard">
                <div className="t">{c.title}</div>
                <span className="pill" style={{
                  background: TINT[s], fontSize: 11 }}>
                  {c.payload?.state ?? s}
                </span>
                <div className="meta">
                  owner：{c.owner || "—"} · 验收：{c.payload?.acceptance
                    ?? "pending"}
                </div>
                <details>
                  <summary>证据与关联</summary>
                  <div className="meta">
                    graph：{c.cycle_id ?? "—"}<br />
                    evidence：{(c.payload?.evidence ?? []).join(", ")
                      || "—"}
                  </div>
                </details>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
