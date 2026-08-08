import { useEffect, useState } from "react";
import { fetchTaskboard } from "../api";

// SLTF §13：任务板 Todo → Running → Waiting → Review → Done。
// 只有用户验收或满足自动验收契约才可进入 Done。
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
      10000);
    return () => clearInterval(t);
  }, []);
  return (
    <div style={{ display: "flex", gap: 12, padding: 12 }}>
      {ORDER.map((s) => (
        <div key={s} style={{ flex: 1, background: "#f6f6f2",
                              border: "1px solid #ccc", padding: 8 }}>
          <h3>{CN[s]} ({(tb[s] ?? []).length})</h3>
          {(tb[s] ?? []).map((e, i) => (
            <div key={i} style={{ background: "#fff", border: "1px solid #ddd",
                                  padding: 6, marginBottom: 6, fontSize: 12 }}>
              <b>{(e.payload_json ?? {}).title ?? e.id.slice(0, 8)}</b>
              <div>{(e.payload_json ?? {}).note ?? ""}</div>
              <div style={{ opacity: 0.6 }}>by {e.by}</div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
