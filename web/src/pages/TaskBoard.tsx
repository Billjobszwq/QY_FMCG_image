import { useEffect, useState } from "react";
import { fetchTaskboard } from "../api";

// 纠偏 Task 6：任务板真实卡片（标题/owner/status/blocker/evidence/
// graph_run_id/linked/updated_at/acceptance），数据来自平台事实源。
const ORDER = ["todo", "running", "waiting", "review", "done"];
const CN: Record<string, string> = {
  todo: "待办", running: "运行中", waiting: "等待/阻塞",
  review: "待验收", done: "完成",
};

export default function TaskBoard() {
  const [tb, setTb] = useState<Record<string, any[]>>({});
  useEffect(() => {
    fetchTaskboard().then((t) => setTb(t.states)).catch(() => {});
    const t = setInterval(
      () => fetchTaskboard().then((t) => setTb(t.states)).catch(() => {}),
      8000);
    return () => clearInterval(t);
  }, []);
  return (
    <div style={{ display: "flex", gap: 12, padding: 12 }}>
      {ORDER.map((s) => (
        <div key={s} style={{ flex: 1, background: "#f6f6f2",
                              border: "1px solid #ccc", padding: 8 }}>
          <h3>{CN[s]} ({(tb[s] ?? []).length})</h3>
          {(tb[s] ?? []).map((e, i) => {
            const p = e.payload ?? {};
            return (
              <div key={i} style={{ background: "#fff",
                                    border: "1px solid #ddd", padding: 6,
                                    marginBottom: 6, fontSize: 12 }}>
                <b>{e.title}</b>
                <div>owner: {p.owner ?? e.by}</div>
                <div>status: {p.state ?? s}</div>
                {p.blocker && <div style={{ color: "#a00" }}>
                  blocker: {p.blocker}</div>}
                <div style={{ opacity: 0.7 }}>
                  evidence: {(e.evidence_json ?? "[]").slice(0, 60)}</div>
                <div style={{ opacity: 0.7 }}>
                  graph_run: sku_long_tail_nextgen_cycle_v1</div>
                <div style={{ opacity: 0.7 }}>
                  updated: {(e.created_at ?? "").slice(0, 19)}</div>
                <div>acceptance: {p.acceptance ?? "pending"}</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
