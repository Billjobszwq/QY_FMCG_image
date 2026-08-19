/**
 * 主管 Agent · 对话（/agent/chat，主管 Agent 组）。
 *
 * 数据源（同源 /api，全部真实数据，禁止样本）：
 * —— POST /api/agent/v1/sessions      （fetchCreateAgentSession：首次发送时创建会话）
 * —— POST /api/agent/v1/chat          （fetchAgentChat：真实工具循环回答 +
 *    command_previews / evidence_refs / ui_intents 留痕）
 * —— GET  /api/v1/blackboard          （fetchBlackboard：右侧黑板最近事件）
 *
 * 数据红线：401 → NeedLoginState；网络错误 → ErrorState；加载中 = 刺猬。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  fetchAgentChat,
  fetchBlackboard,
  fetchCreateAgentSession,
} from "@/lib/api";
import {
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** 请求桌面层打开登录窗口（与既有页面同源约定）。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

const fmtAt = (s: string | null | undefined) =>
  s ? s.slice(0, 19).replace("T", " ") : "—";

/** 一条对话消息（命令预览与证据随主管回答一起呈现，供追溯）。 */
interface ChatMsg {
  role: "user" | "agent" | "err";
  text: string;
  commands?: Array<{ command_id: string; kind: string }>;
  evidence?: string[];
}

/** 黑板事件（后端 blackboard_event_v1 行；字段防御性取值）。 */
interface BoardEvent {
  id?: string;
  by?: string;
  by_kind?: string;
  event_type?: string;
  payload_json?: string;
  created_at?: string;
}

/** 黑板事件摘要：从 payload_json 提取一句可读文本（失败回退原文截断）。 */
function payloadDigest(ev: BoardEvent): string {
  if (!ev.payload_json) return "—";
  try {
    const p = JSON.parse(ev.payload_json) as Record<string, unknown>;
    for (const k of ["summary", "message", "text", "title"]) {
      const v = p[k];
      if (typeof v === "string" && v.trim()) return v;
    }
    return JSON.stringify(p);
  } catch {
    return ev.payload_json;
  }
}

export default function AgentChat() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [needLogin, setNeedLogin] = useState(false);
  /** 会话 id：首次发送时才创建（与 web 主管工作台同策略）。 */
  const sessionIdRef = useRef<string | null>(null);
  const [sessionNote, setSessionNote] = useState<string | null>(null);
  // 黑板最近事件
  const [events, setEvents] = useState<BoardEvent[] | null>(null);
  const [eventsErr, setEventsErr] = useState<unknown>(null);
  const [events401, setEvents401] = useState(false);

  const loadBoard = useCallback(async () => {
    setEventsErr(null);
    setEvents401(false);
    try {
      const d = await fetchBlackboard();
      // 最近事件在前；只取最近 12 条，避免长列表噪音。
      setEvents([...(d.events as BoardEvent[])].reverse().slice(0, 12));
    } catch (e) {
      setEvents(null);
      if (is401(e)) setEvents401(true);
      else setEventsErr(e);
    }
  }, []);

  useEffect(() => {
    void loadBoard();
  }, [loadBoard]);

  /** 新会话：丢弃当前会话 id 与消息流（历史仍由服务端保存）。 */
  function resetSession() {
    sessionIdRef.current = null;
    setMsgs([]);
    setSessionNote(null);
    setNeedLogin(false);
  }

  /** 发送：无会话先创建；回答携带命令预览 / 证据引用一并留痕展示。 */
  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setNeedLogin(false);
    setInput("");
    setMsgs((m) => [...m, { role: "user", text }]);
    try {
      if (!sessionIdRef.current) {
        sessionIdRef.current = await fetchCreateAgentSession("桌面主管工作台");
        setSessionNote(`会话已创建：${sessionIdRef.current.slice(0, 12)}…`);
      }
      const d = await fetchAgentChat(sessionIdRef.current, text);
      const commands = Array.isArray(d?.command_previews)
        ? d.command_previews.map((c: Record<string, unknown>) => ({
            command_id: String(c.command_id ?? ""),
            kind: String(c.kind ?? ""),
          }))
        : undefined;
      const evidence = Array.isArray(d?.evidence_refs)
        ? d.evidence_refs.map((r: unknown) =>
            typeof r === "string"
              ? r
              : `${(r as Record<string, unknown>)?.kind ?? "证据"}: ${
                  (r as Record<string, unknown>)?.ref ?? ""
                }`,
          )
        : undefined;
      setMsgs((m) => [
        ...m,
        {
          role: "agent",
          text: typeof d?.message === "string" ? d.message : "（无回答内容）",
          commands,
          evidence,
        },
      ]);
      // 有新命令预览时刷新黑板（事件可能随工具循环落板）。
      if (commands && commands.length > 0) void loadBoard();
    } catch (err) {
      if (is401(err)) {
        setNeedLogin(true);
      } else {
        setMsgs((m) => [
          ...m,
          { role: "err", text: `发送失败：${errorMessageOf(err)}` },
        ]);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="主管 Agent · 对话"
        desc="真实工具循环回答；写命令先落待批准账本，批准后才执行"
        aside={
          <>
            {sessionNote && (
              <span className="text-xs text-text-secondary">{sessionNote}</span>
            )}
            <Button variant="secondary" size="sm" onClick={resetSession}>
              新会话
            </Button>
          </>
        }
      />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
        {/* ---- 左：消息流 + 输入 ---- */}
        <section className="space-y-2" aria-label="主管 Agent 对话">
          {needLogin ? (
            <NeedLoginState onOpenLogin={openLogin} />
          ) : (
            <>
              <div className="max-h-[420px] min-h-[240px] space-y-2 overflow-y-auto rounded-md border border-border bg-surface/60 p-3">
                {msgs.length === 0 && (
                  <p className="text-[13px] text-text-secondary">
                    你好，我是主管 Agent。可以问我识别任务、训练进度、阻塞与
                    待批准命令；也可以让我生成写命令预览（批准后执行）。
                  </p>
                )}
                {msgs.map((m, i) => (
                  <div key={i} className="space-y-1">
                    <div
                      className={
                        m.role === "user"
                          ? "ml-8 rounded-md border border-border bg-background p-2"
                          : "mr-8 rounded-md border border-border bg-surface p-2"
                      }
                    >
                      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-text-primary">
                        {m.role === "err" ? (
                          <StatusBadge kind="serious">{m.text}</StatusBadge>
                        ) : (
                          m.text
                        )}
                      </p>
                    </div>
                    {(m.commands ?? []).map((c) => (
                      <p key={c.command_id} className="mr-8 flex items-center gap-2 pl-1">
                        <StatusBadge kind="warn">待批准</StatusBadge>
                        <span className="min-w-0 truncate text-xs text-text-secondary">
                          命令 {c.command_id} · {c.kind || "未知类型"}（在「命令审批」标签处理）
                        </span>
                      </p>
                    ))}
                    {(m.evidence ?? []).map((ev, j) => (
                      <p key={j} className="mr-8 truncate pl-1 text-xs text-text-secondary">
                        证据：{ev}
                      </p>
                    ))}
                  </div>
                ))}
                {busy && (
                  <p className="text-xs text-text-secondary">主管思考中…</p>
                )}
              </div>
              <form className="flex gap-2" onSubmit={(e) => void send(e)}>
                <Input
                  value={input}
                  placeholder="问主管 Agent…（Enter 发送）"
                  aria-label="主管 Agent 输入"
                  className="flex-1"
                  onChange={(e) => setInput(e.target.value)}
                />
                <Button type="submit" size="sm" className="h-8" disabled={busy || !input.trim()}>
                  发送
                </Button>
              </form>
            </>
          )}
        </section>

        {/* ---- 右：黑板最近事件 ---- */}
        <aside className="space-y-2" aria-label="黑板最近事件">
          <h2 className="text-[13px] font-semibold text-text-primary">
            黑板 · 最近事件
          </h2>
          {events401 ? (
            <NeedLoginState onOpenLogin={openLogin} />
          ) : eventsErr ? (
            <ErrorState
              message={errorMessageOf(eventsErr)}
              onRetry={() => void loadBoard()}
            />
          ) : events === null ? (
            <p className="text-xs text-text-secondary">加载中…</p>
          ) : events.length === 0 ? (
            <p className="text-xs text-text-secondary">
              黑板暂无事件：Agent 的结论与提醒会写在这里
            </p>
          ) : (
            <ul className="space-y-1.5">
              {events.map((ev, i) => (
                <li
                  key={ev.id ?? i}
                  className="rounded-md border border-border bg-surface/60 p-2"
                >
                  <p className="flex items-center gap-1.5">
                    <StatusBadge kind="neutral">{ev.event_type ?? "事件"}</StatusBadge>
                    <span className="text-xs text-text-secondary">
                      {ev.by ?? "系统"}
                      {ev.by_kind === "human" ? "（人工）" : ""}
                    </span>
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-text-primary">
                    {payloadDigest(ev)}
                  </p>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {fmtAt(ev.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}
