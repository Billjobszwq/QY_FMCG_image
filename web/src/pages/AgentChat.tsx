import { useEffect, useRef, useState } from "react";
import { csrfToken } from "../api";

// Agent 聊天：后端 /api/agent/v1/chat（DeepSeek + 平台工具），
// 前端保证反馈：发送态/打字态/错误态/会话持久化。
interface Msg { role: "user" | "agent" | "err"; text: string; }

export default function AgentChat() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sidRef = useRef<string | null>(
    localStorage.getItem("agent_session_v2"));
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: 999999 });
  }, [msgs, open]);

  // 恢复历史
  useEffect(() => {
    if (sidRef.current) {
      fetch(`/api/agent/v1/sessions/${sidRef.current}/messages`)
        .then((r) => (r.ok ? r.json() : { messages: [] }))
        .then((d) =>
          setMsgs((d.messages ?? []).map((m: any) => ({
            role: m.role === "user" ? "user" : "agent",
            text: m.content,
          }))))
        .catch(() => {});
    }
  }, []);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");
    setMsgs((m) => [...m, { role: "user", text },
      { role: "agent", text: "…" }]);
    try {
      if (!sidRef.current) {
        const r = await fetch("/api/agent/v1/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json",
            ...(csrfToken() ? { "X-CSRF-Token": csrfToken() as string }
              : {}) },
          credentials: "include",
          body: JSON.stringify({ title: "chat" }),
        });
        sidRef.current = (await r.json()).session_id;
        localStorage.setItem("agent_session_v2", sidRef.current as string);
      }
      const r = await fetch("/api/agent/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json",
          ...(csrfToken() ? { "X-CSRF-Token": csrfToken() as string } : {}) },
        credentials: "include",
        body: JSON.stringify({ session_id: sidRef.current, text }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setMsgs((m) => {
        const cp = [...m];
        cp[cp.length - 1] = { role: "agent", text: d.answer ?? d.error };
        return cp;
      });
    } catch (e) {
      setMsgs((m) => {
        const cp = [...m];
        cp[cp.length - 1] = {
          role: "err",
          text: `发送失败：${e instanceof Error ? e.message : e}`,
        };
        return cp;
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button className="agent-fab" onClick={() => setOpen(!open)}
        title="主管 Agent">✦</button>
      {open && (
        <div className="agent-panel">
          <div className="agent-head">主管 Agent · DeepSeek</div>
          <div className="agent-msgs" ref={boxRef}>
            {msgs.length === 0 && (
              <div className="msg agent">
                你好，我是主管 Agent。可以问我：训练进度、候选模型、
                数据缺口、工作流状态，或让我打开页面、创建计划。
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>{m.text}</div>
            ))}
          </div>
          <div className="agent-input">
            <input value={input} placeholder="问 Agent…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()} />
            <button className="btn violet" style={{ padding: "10px 18px" }}
              disabled={busy} onClick={send}>发送</button>
          </div>
        </div>
      )}
    </>
  );
}
