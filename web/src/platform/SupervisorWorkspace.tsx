// ABOS T6/T9：主管工作台（右侧全局工作区）。
// 黄色便签/任务板语言：今日待办/需要批准/正在运行/异常/最近完成，
// 全部来自 Domain Service projection；对话消费统一 Agent 契约
// （message/evidence_refs/ui_intents/command_previews/delegations）。
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  agentChat, approveAgentCommand, confirmGoal, createAgentSession,
  createNote, deleteNote, fetchGoal, fetchGoals, fetchNotes, fetchWorkItems,
  GoalDraft, HomeNote, rejectAgentCommand, WorkItemsBody,
} from "../api";

const ALLOWED_INTENTS = ["navigate", "open_panel", "filter", "highlight",
  "compare", "pin", "pin_card", "show_evidence"];

interface Msg {
  role: "user" | "agent" | "err";
  text: string;
  intents?: any[];
  commands?: any[];
  evidence?: any[];
  delegations?: any[];
  traceId?: string;
}

function execIntent(intent: any, navigate: (to: string) => void): string {
  // UIIntent 白名单执行：只接受结构化 kind+target，禁 HTML/JS 注入
  const kind = intent?.kind;
  if (!ALLOWED_INTENTS.includes(kind)) return `忽略非法 intent: ${kind}`;
  const target = intent?.target;
  if (kind === "navigate" && typeof target === "string"
      && target.startsWith("/")) {
    navigate(target);
    return `已跳转到 ${target}`;
  }
  return `已记录 ${kind}: ${JSON.stringify(target)}`;
}

export function CommandPreviewCard({ cmd, onDone }:
  { cmd: any; onDone: (note: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [resolved, setResolved] = useState<string | null>(null);
  const params = cmd.params ?? {};
  if (resolved) {
    return <div className="delegation">命令 {cmd.command_id}：{resolved}</div>;
  }
  return (
    <div className="cmd-preview">
      <div className="row"><b>命令</b><span>{cmd.kind}</span></div>
      {Object.entries(params).map(([k, v]) => (
        <div className="row" key={k}><b>{k}</b>
          <span>{typeof v === "string" ? v : JSON.stringify(v)}</span></div>
      ))}
      {cmd.impact && <div className="row"><b>影响</b>
        <span>{cmd.impact}</span></div>}
      {cmd.cost_estimate && <div className="row"><b>成本</b>
        <span>{cmd.cost_estimate}</span></div>}
      {cmd.idempotency_key && <div className="row"><b>幂等键</b>
        <span style={{ fontFamily: "var(--font-mono)" }}>
          {cmd.idempotency_key}</span></div>}
      {cmd.rollback && <div className="row"><b>回滚</b>
        <span>{cmd.rollback}</span></div>}
      <div className="cmd-actions">
        <button className="btn small primary" disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const d = await approveAgentCommand(cmd.command_id);
              const note = `已批准${d.execution?.task_id
                ? ` 并创建任务 ${d.execution.task_id}` : ""}`;
              setResolved(note); onDone(note);
            } catch (e) {
              const note = `批准失败：${e instanceof Error ? e.message : e}`;
              setResolved(note); onDone(note);
            } finally { setBusy(false); }
          }}>批准并执行</button>
        <button className="btn small danger" disabled={busy}
          onClick={async () => {
            setBusy(true);
            try { await rejectAgentCommand(cmd.command_id);
              setResolved("已拒绝"); onDone("已拒绝"); }
            catch (e) {
              const note = `拒绝失败：${e instanceof Error ? e.message : e}`;
              setResolved(note); onDone(note);
            } finally { setBusy(false); }
          }}>拒绝</button>
      </div>
    </div>
  );
}

export default function SupervisorWorkspace() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<"board" | "chat">("board");
  // ABOSV2-P1-006：≥1440 可 dock；1024–1439 默认收起（打开为不透明
  // 临时抽屉，不遮挡主内容）；<1024 全屏抽屉。
  const [open, setOpen] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.innerWidth >= 1440 : true);

  const [work, setWork] = useState<WorkItemsBody | null>(null);
  const [workErr, setWorkErr] = useState<string | null>(null);
  const [pendingGoal, setPendingGoal] = useState<GoalDraft | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // ABOSV3-P2-001→服务端：便签不再存 localStorage，服务端持久化
  const [notes, setNotes] = useState<HomeNote[]>([]);
  const [noteInput, setNoteInput] = useState("");
  // ABOSV3-P1-001：桌面端可拖拽调宽 360–480px（偏好可持久）
  const [panelW, setPanelW] = useState<number>(() => {
    const w = Number(localStorage.getItem("abos_side_w") || 0);
    return w >= 360 && w <= 480 ? w : 400;
  });
  const resizingRef = useRef(false);
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (!resizingRef.current) return;
      const w = Math.min(480, Math.max(360, window.innerWidth - e.clientX));
      setPanelW(w);
    };
    const up = () => {
      if (resizingRef.current) {
        resizingRef.current = false;
        setPanelW((w) => {
          localStorage.setItem("abos_side_w", String(w));
          return w;
        });
      }
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);
  const sidRef = useRef<string | null>(
    localStorage.getItem("agent_session_v2"));
  const boxRef = useRef<HTMLDivElement>(null);

  // ABOSV2-P0-002：首页快速目标携带 goal_id 进入主管：
  // 拉回服务端 goal_draft → 同一文本进输入框；确认后形成计划/命令。
  useEffect(() => {
    const goalId = searchParams.get("goal");
    if (searchParams.get("focus") === "chat" || goalId) {
      setOpen(true);
      setTab("chat");
      searchParams.delete("focus");
      searchParams.delete("goal");
      setSearchParams(searchParams, { replace: true });
      if (goalId) {
        fetchGoal(goalId).then((g) => {
          if (g.status === "open") {
            setPendingGoal(g);
            setInput(g.text);
          }
        }).catch(() => { /* goal 不存在时诚实降级为普通对话 */ });
      }
    }
  }, [searchParams, setSearchParams]);

  // 刷新恢复：未处理的 open goal 自动回到主管输入框（不依赖前端状态）
  useEffect(() => {
    fetchGoals("open").then((d) => {
      if (d.goals.length > 0) {
        setPendingGoal((cur) => cur ?? d.goals[0]);
        setInput((cur) => cur || d.goals[0].text);
      }
    }).catch(() => { /* 未登录/服务异常：不静默伪造 */ });
  }, []);

  useEffect(() => {
    // 便签从服务端加载（刷新/跨浏览器一致）
    fetchNotes().then((d) => setNotes(d.notes)).catch(() => { /* 未登录 */ });
  }, []);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [msgs, tab]);

  const loadWork = useCallback(() => {
    fetchWorkItems().then(setWork).catch(
      (e) => setWorkErr(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => {
    loadWork();
    const t = setInterval(() => {
      // 后台轮询降频：页面不可见时跳过
      if (document.visibilityState === "visible") loadWork();
    }, 30000);
    return () => clearInterval(t);
  }, [loadWork]);

  useEffect(() => {
    if (sidRef.current) {
      fetch(`/api/agent/v1/sessions/${sidRef.current}/messages`)
        .then((r) => (r.ok ? r.json() : { messages: [] }))
        .then((d) => setMsgs((d.messages ?? []).map((m: any) => {
          let meta: any = {};
          try { meta = JSON.parse(m.meta_json ?? "{}"); } catch { /* noop */ }
          return {
            role: m.role === "user" ? "user" : "agent",
            text: m.content,
            intents: meta.ui_intents, commands: meta.command_previews,
            evidence: meta.evidence_refs, delegations: meta.delegations,
            traceId: meta.trace_id,
          };
        })))
        .catch(() => { /* 会话失效时重新开始 */ });
    }
  }, []);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true); setInput("");
    setMsgs((m) => [...m, { role: "user", text },
      { role: "agent", text: "…" }]);
    try {
      if (!sidRef.current) {
        sidRef.current = await createAgentSession("workbench");
        localStorage.setItem("agent_session_v2", sidRef.current);
      }
      const d = await agentChat(sidRef.current, text);
      const intentNotes: string[] = [];
      for (const it of d.ui_intents ?? []) {
        intentNotes.push(execIntent(it, navigate));
      }
      setMsgs((m) => {
        const cp = [...m];
        cp[cp.length - 1] = {
          role: "agent",
          text: (d.message ?? "") + (intentNotes.length
            ? "\n（" + intentNotes.join("；") + "）" : ""),
          intents: d.ui_intents, commands: d.command_previews,
          evidence: d.evidence_refs, delegations: d.delegations,
          traceId: d.trace_id,
        };
        return cp;
      });
      if ((d.command_previews ?? []).length) loadWork();
      // 目标已发送：服务端确认 goal，留痕计划/命令/trace
      if (pendingGoal) {
        confirmGoal(pendingGoal.goal_id)
          .catch(() => { /* 确认失败不阻断对话；goal 仍为 open 可重试 */ })
          .finally(() => setPendingGoal(null));
      }
    } catch (e) {
      setMsgs((m) => {
        const cp = [...m];
        cp[cp.length - 1] = {
          role: "err",
          text: `发送失败：${e instanceof Error ? e.message : e}`,
        };
        return cp;
      });
    } finally { setBusy(false); }
  };

  const addNote = async () => {
    const t = noteInput.trim();
    if (!t) return;
    try {
      await createNote(t);
      setNoteInput("");
      const d = await fetchNotes();
      setNotes(d.notes);
    } catch { /* 保存失败时不静默丢失：输入保留 */ }
  };

  const s = work?.summary;
  const groups: Array<{ key: string; title: string; cls: string;
    items: any[] }> = [
    { key: "approval", title: "需要批准", cls: "approval",
      items: (work?.items ?? []).filter((i) =>
        i.kind.includes("approval") || i.stage === "approval") },
    { key: "blocked", title: "异常 / 阻塞", cls: "blocked",
      items: (work?.items ?? []).filter((i) =>
        i.status === "blocked" || i.status_text?.includes("阻塞")) },
    { key: "running", title: "正在运行", cls: "running",
      items: (work?.items ?? []).filter((i) =>
        i.status === "active" || i.status === "running") },
    { key: "todo", title: "今日待办", cls: "",
      items: (work?.items ?? []).filter((i) =>
        i.kind.includes("todo") || i.stage === "todo") },
  ];

  return (
    <>
      {!open && (
        <button className="agent-fab" aria-label="打开主管工作台"
          onClick={() => setOpen(true)}>✦</button>
      )}
      {open && (
    <aside className="side-panel" aria-label="主管工作台"
      style={window.innerWidth >= 1440 ? { width: panelW } : undefined}>
      {window.innerWidth >= 1440 && (
        <div className="side-resize" role="separator"
          aria-label="拖拽调整主管工作台宽度"
          onMouseDown={() => { resizingRef.current = true; }} />
      )}
      <div className="side-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "board"}
          className={tab === "board" ? "active" : ""}
          onClick={() => setTab("board")}>任务板</button>
        <button role="tab" aria-selected={tab === "chat"}
          className={tab === "chat" ? "active" : ""}
          onClick={() => setTab("chat")}>主管 Agent</button>
        <button aria-label="收起主管工作台" style={{ flex: "0 0 auto",
          padding: "9px 10px", border: "none", background: "transparent",
          cursor: "pointer", color: "var(--text-muted)" }}
          onClick={() => setOpen(false)}>✕</button>
      </div>
      {tab === "board" ? (
        <div className="side-body">
          {workErr && (
            <div className="banner banner-error">
              任务板加载失败：{workErr}
              <div className="next">
                <button className="btn small" onClick={() => {
                  setWorkErr(null); loadWork(); }}>重试</button>
              </div>
            </div>
          )}
          {!work && !workErr && <p className="muted">加载中…</p>}
          {work && groups.map((g) => (
            <div key={g.key}>
              <h3 style={{ fontSize: 13, margin: "10px 0 6px" }}>
                {g.title}（{g.items.length}）
              </h3>
              {g.items.length === 0 ? (
                <p className="v" style={{ margin: "0 0 6px" }}>
                  暂无 · 有新事项会出现在这里</p>
              ) : g.items.slice(0, 8).map((it) => (
                <div key={it.id} className={`note-card ${g.cls}`}>
                  <div>{it.title}</div>
                  <div className="meta">{it.kind} · {it.status_text}
                    {it.owner ? ` · ${it.owner}` : ""}</div>
                </div>
              ))}
            </div>
          ))}
          {s && (s.blocked?.length || s.next_steps?.length) ? (
            <div className="card" style={{ marginTop: 8 }}>
              <h3>下一步</h3>
              {s.next_steps.map((n) => <p key={n} className="v">· {n}</p>)}
              {s.blocked.map((b) => (
                <p key={b} className="v" style={{ color: "var(--err)" }}>
                  ⚠ {b}</p>))}
            </div>
          ) : null}
          <h3 style={{ fontSize: 13, margin: "12px 0 6px" }}>固定笔记</h3>
          <div style={{ display: "flex", gap: 6 }}>
            <input style={{ flex: 1 }} value={noteInput}
              placeholder="记一条笔记…"
              onChange={(e) => setNoteInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addNote()} />
            <button className="btn small" onClick={addNote}>固定</button>
          </div>
          {notes.map((n) => (
            <div key={n.note_id} className="note-card"
              style={{ marginTop: 8, display: "flex",
                justifyContent: "space-between", gap: 6 }}>
              <span>{n.pinned ? "📌 " : ""}{n.content}</span>
              <button className="btn small" aria-label="删除笔记"
                onClick={async () => {
                  await deleteNote(n.note_id);
                  const d = await fetchNotes(); setNotes(d.notes);
                }}>×</button>
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="agent-msgs side-body" ref={boxRef}>
            {msgs.length === 0 && (
              <div className="msg agent">
                你好，我是主管 Agent。可以问我：识别任务、候选模型、
                训练进度、阻塞；或让我打开页面、生成识别命令预览
                （批准后执行）。
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} style={{ display: "flex",
                flexDirection: "column" }}>
                <div className={`msg ${m.role}`}>{m.text}</div>
                {(m.evidence ?? []).length > 0 && (
                  <ul className="evidence-list">
                    {(m.evidence ?? []).map((e: any, j: number) => (
                      <li key={j}>证据：{typeof e === "string"
                        ? e : `${e.kind}: ${e.ref}`}</li>))}
                  </ul>
                )}
                {(m.delegations ?? []).map((d: any, j: number) => (
                  <div key={j} className="delegation">
                    委派 {d.agent_id} · {d.action} · {d.status}
                  </div>
                ))}
                {(m.commands ?? []).map((c: any) => (
                  <CommandPreviewCard key={c.command_id} cmd={c}
                    onDone={(note) => setMsgs((ms) => {
                      const cp = [...ms];
                      cp.push({ role: "agent", text: note });
                      return cp;
                    })} />
                ))}
              </div>
            ))}
          </div>
          <div className="agent-input">
            {pendingGoal && (
              <p className="v" style={{ margin: "0 0 4px",
                fontSize: 12, color: "var(--text-muted)" }}>
                待确认目标（goal:{pendingGoal.goal_id.slice(-6)}）：
                发送后由主管形成计划/命令并留痕</p>
            )}
            <input value={input} placeholder="问主管 Agent…"
              aria-label="主管 Agent 输入"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()} />
            <button className="btn primary" disabled={busy}
              onClick={send}>{busy ? "等待…" : "发送"}</button>
          </div>
        </>
      )}
    </aside>
      )}
    </>
  );
}
