import { useCallback, useEffect, useRef, useState } from "react";
import { csrfToken, fetchAgents, fetchBlackboard,
  fetchTaskboard } from "../api";

// 纠偏 Task 6：主管抽屉（可读对比度 + 对话输入 + 会话历史 + 命令审批）。
// 数据全部来自平台事实源（blackboard/taskboard/agents/sessions）。
const api = (p: string, o?: RequestInit) =>
  fetch(p, {
    headers: { "Content-Type": "application/json",
               ...(csrfToken() ? { "X-CSRF-Token": csrfToken() as string }
                   : {}) },
    credentials: "include",
    ...o,
  });

export default function SupervisorDrawer() {
  const [open, setOpen] = useState(false);
  const [bb, setBb] = useState<any[]>([]);
  const [tb, setTb] = useState<Record<string, any[]>>({});
  const [agents, setAgents] = useState<any[]>([]);
  const [msgs, setMsgs] = useState<any[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sidRef = useRef<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

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
      if (sidRef.current) {
        const m = await api(
          `/api/agent/v1/sessions/${sidRef.current}/messages`);
        if (m.ok) setMsgs((await m.json()).messages);
      }
    } catch { /* 抽屉失败不阻塞页面 */ }
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 8000);
    return () => clearInterval(t);
  }, [reload]);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: 999999 });
  }, [msgs]);

  const send = async () => {
    if (!input.trim() || busy) return;
    setBusy(true);
    try {
      if (!sidRef.current) {
        const r = await api("/api/agent/v1/sessions", {
          method: "POST", body: JSON.stringify({ title: "drawer" }),
        });
        sidRef.current = (await r.json()).session_id;
      }
      await api("/api/agent/v1/chat", {
        method: "POST",
        body: JSON.stringify({ session_id: sidRef.current, text: input }),
      });
      setInput("");
      await reload();
    } finally { setBusy(false); }
  };

  const decide = async (cmdId: string, act: "approve" | "reject") => {
    await api(`/api/agent/v1/commands/${cmdId}/${act}`, { method: "POST" });
    await reload();
  };

  const commands = msgs.flatMap((m) =>
    m.role === "supervisor"
      ? (JSON.parse(m.meta_json || "{}").commands ?? [])
      : []);

  const sec = (title: string, items: any[]) => (
    <div style={{ marginBottom: 10 }}>
      <b style={{ color: "#5a4500" }}>{title}</b>
      {items.length === 0 ? (
        <div style={{ color: "#7a6a30", fontSize: 12 }}>（空）</div>
      ) : (
        items.slice(-5).map((e, i) => (
          <div key={i} style={{ fontSize: 12, color: "#332b00",
                                borderBottom: "1px dashed #c9a94a" }}>
            [{e.by ?? e.owner}]{" "}
            {(e.payload ?? JSON.parse(e.payload_json || "{}")).title ??
             (e.payload ?? JSON.parse(e.payload_json || "{}")).text}
          </div>
        ))
      )}
    </div>
  );

  return (
    <div style={{ position: "fixed", right: 0, top: 0, bottom: 0,
                  width: open ? 360 : 36, background: "#fff7d6",
                  borderLeft: "2px solid #d9a520", transition: "width .2s",
                  zIndex: 50, overflowY: "auto", padding: 8,
                  boxShadow: "-2px 0 8px rgba(0,0,0,.2)" }}>
      <button onClick={() => setOpen(!open)}
        style={{ width: "100%", background: "#d9a520", border: 0,
                 fontWeight: 700, cursor: "pointer", color: "#221a00" }}>
        {open ? "收起主管笔记 ▸" : "◂ 主管"}
      </button>
      {open && (
        <>
          <div ref={boxRef} style={{ maxHeight: 180, overflowY: "auto",
                                     background: "#fffbe8", padding: 6,
                                     border: "1px solid #e0c060" }}>
            {msgs.map((m, i) => (
              <div key={i} style={{ fontSize: 12, color: "#222",
                                    margin: "3px 0" }}>
                <b>{m.role}：</b>{m.content}
              </div>
            ))}
            {msgs.length === 0 &&
              <div style={{ color: "#7a6a30", fontSize: 12 }}>
                输入问题，如“目前训练到哪里？”
              </div>}
          </div>
          <div style={{ display: "flex", gap: 4, margin: "6px 0" }}>
            <input value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="问主管 Agent…"
              style={{ flex: 1, padding: 4, color: "#222" }} />
            <button onClick={send} disabled={busy}
              style={{ background: "#d9a520", border: 0, color: "#221a00" }}>
              发送
            </button>
          </div>
          {commands.filter((c: any) => c.status === "pending_approval")
            .map((c: any) => (
              <div key={c.command_id} style={{ fontSize: 12, color: "#222",
                                               margin: "4px 0" }}>
                命令预览：{c.kind}
                <button onClick={() => decide(c.command_id, "approve")}
                  style={{ marginLeft: 6 }}>批准</button>
                <button onClick={() => decide(c.command_id, "reject")}>
                  拒绝</button>
              </div>
            ))}
          {sec("今日待办", tb["todo"] ?? [])}
          {sec("Running", tb["running"] ?? [])}
          {sec("Waiting / Blocked", [
            ...(tb["waiting"] ?? []),
            ...bb.filter((e) => e.event_type === "Blocker")])}
          {sec("Needs Review", tb["review"] ?? [])}
          {sec("Resolved", [
            ...(tb["done"] ?? []),
            ...bb.filter((e) => e.event_type === "Resolution")])}
          <div style={{ marginBottom: 8 }}>
            <b style={{ color: "#5a4500" }}>Agent 健康</b>
            {agents.map((a) => (
              <div key={a.agent_id} style={{ fontSize: 12, color: "#332b00" }}>
                ● {a.agent_id} · {a.domain} · risk={a.risk_level}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
