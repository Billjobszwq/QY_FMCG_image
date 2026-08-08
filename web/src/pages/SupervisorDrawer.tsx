import { useCallback, useEffect, useState } from "react";
import { fetchAgents, fetchBlackboard, fetchTaskboard } from "../api";

// SLTF §13：跨页面黄色"主管笔记"抽屉。
// 含：对话区(只读事件流)/今日待办/Running/Waiting/Needs Review/Resolved/
// 资源状态/Agent 健康。数据来自 blackboard/taskboard/agents API。
export default function SupervisorDrawer() {
  const [open, setOpen] = useState(false);
  const [bb, setBb] = useState<any[]>([]);
  const [tb, setTb] = useState<Record<string, any[]>>({});
  const [agents, setAgents] = useState<any[]>([]);

  const reload = useCallback(async () => {
    try {
      const [b, t, a] = await Promise.all([
        fetchBlackboard().catch(() => ({ events: [] })),
        fetchTaskboard().catch(() => ({ states: {} })),
        fetchAgents().catch(() => ({ agents: [] })),
      ]);
      setBb(b.events);
      setTb(t.states);
      setAgents(a.agents);
    } catch {
      /* 抽屉失败不阻塞页面 */
    }
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 10000);
    return () => clearInterval(t);
  }, [reload]);

  const sec = (title: string, items: any[]) => (
    <div style={{ marginBottom: 10 }}>
      <b>{title}</b>
      {items.length === 0 ? (
        <div style={{ opacity: 0.6, fontSize: 12 }}>（空）</div>
      ) : (
        items.slice(-6).map((e, i) => (
          <div key={i} style={{ fontSize: 12, borderBottom: "1px dashed #caa" }}>
            [{e.by}] {e.event_type}:{" "}
            {JSON.stringify(e.payload_json ?? {}).slice(0, 60)}
          </div>
        ))
      )}
    </div>
  );

  return (
    <div
      style={{
        position: "fixed",
        right: 0,
        top: 0,
        bottom: 0,
        width: open ? 340 : 36,
        background: "#fff7d6",
        borderLeft: "2px solid #d9a520",
        transition: "width .2s",
        zIndex: 50,
        overflowY: "auto",
        padding: 8,
        boxShadow: "-2px 0 8px rgba(0,0,0,.15)",
      }}
    >
      <button onClick={() => setOpen(!open)}
        style={{ width: "100%", background: "#d9a520", border: 0,
                 fontWeight: 700, cursor: "pointer" }}>
        {open ? "收起主管笔记 ▸" : "◂ 主管"}
      </button>
      {open && (
        <>
          {sec("今日待办 (Task/todo)", tb["todo"] ?? [])}
          {sec("Running", tb["running"] ?? [])}
          {sec("Waiting / Blocked", [
            ...(tb["waiting"] ?? []),
            ...bb.filter((e) => e.event_type === "Blocker"),
          ])}
          {sec("Needs Review", tb["review"] ?? [])}
          {sec("Resolved", [
            ...(tb["done"] ?? []),
            ...bb.filter((e) => e.event_type === "Resolution"),
          ])}
          <div style={{ marginBottom: 10 }}>
            <b>Agent 健康</b>
            {agents.map((a) => (
              <div key={a.agent_id} style={{ fontSize: 12 }}>
                ● {a.agent_id} · {a.domain} · risk={a.risk_level}
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, opacity: 0.7 }}>
            黑板 append-only；命令预览/批准需登录 + CSRF。
          </div>
        </>
      )}
    </div>
  );
}
