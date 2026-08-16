/**
 * 连接器（/workflow/connectors）—— 适配器诚实状态 + 黑板事件 + 便签留言（瘦版重实现）。
 *
 * 数据源（同源 /api/v1，全部真实数据，禁止样本）：
 * —— GET  /api/v1/workflows/node-library → connectors（n8n / Dify 适配器可用性与原因；
 *    web 端更准确的连接器端点，未许可一律诚实 blocked）
 * —— GET  /api/v1/blackboard（append-only 黑板事件台账）
 * —— GET  /api/v1/notes、POST /api/v1/notes（留言视角：创建便签）
 */
import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ApiError,
  fetchBlackboard,
  fetchCreateNote,
  fetchNodeLibrary,
  fetchNotes,
} from "@/lib/api";
import type { HomeNote } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HedgehogMascot } from "@/components/ui/mascot";

/* ============================================================================
   小工具（页面内私有）
   ========================================================================== */

/** 请求桌面层打开登录窗口。 */
const openLogin = () => window.dispatchEvent(new Event("platform:open-login"));

const is401 = (err: unknown) => err instanceof ApiError && err.status === 401;

const fmtAt = (s: string | null | undefined) =>
  s ? s.slice(0, 19).replace("T", " ") : "—";

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s);

/** 黑板事件行（blackboard_event_v1 投影）。 */
interface BlackboardEvent {
  id: string;
  by: string;
  by_kind: string;
  event_type: string;
  payload_json: string;
  created_at: string;
}

type Msg = { kind: "good" | "serious"; text: string };

function ActionMsg({ msg }: { msg: Msg | null }) {
  if (!msg) return null;
  return (
    <div className="flex items-center gap-2">
      <StatusBadge kind={msg.kind}>{msg.kind === "good" ? "操作成功" : "操作失败"}</StatusBadge>
      <p className="min-w-0 truncate text-xs text-text-secondary">{msg.text}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-[13px] font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}

/* ============================================================================
   页面
   ========================================================================== */

export default function Connectors() {
  // 连接器状态（node-library.connectors）
  const [connectors, setConnectors] = useState<Record<
    string,
    { available: boolean; reason: string }
  > | null>(null);
  const [connErr, setConnErr] = useState<unknown>(null);
  // 黑板事件
  const [events, setEvents] = useState<BlackboardEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsErr, setEventsErr] = useState<unknown>(null);
  const [events401, setEvents401] = useState(false);
  // 便签留言
  const [notes, setNotes] = useState<HomeNote[]>([]);
  const [notesLoading, setNotesLoading] = useState(true);
  const [notesErr, setNotesErr] = useState<unknown>(null);
  const [notes401, setNotes401] = useState(false);
  // 表单
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg | null>(null);

  const loadConnectors = useCallback(async () => {
    setConnErr(null);
    try {
      const lib = await fetchNodeLibrary();
      setConnectors(lib.connectors);
    } catch (e) {
      setConnectors(null);
      setConnErr(e);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsErr(null);
    setEvents401(false);
    try {
      const d = await fetchBlackboard();
      // 后端按时间正序返回；台账视角展示最近 30 条，倒序在前
      const rows = (d.events as BlackboardEvent[]).slice(-30).reverse();
      setEvents(rows);
    } catch (e) {
      if (is401(e)) setEvents401(true);
      else setEventsErr(e);
    } finally {
      setEventsLoading(false);
    }
  }, []);

  const loadNotes = useCallback(async () => {
    setNotesLoading(true);
    setNotesErr(null);
    setNotes401(false);
    try {
      const d = await fetchNotes();
      setNotes([...d.notes].sort((a, b) => b.created_at.localeCompare(a.created_at)));
    } catch (e) {
      if (is401(e)) setNotes401(true);
      else setNotesErr(e);
    } finally {
      setNotesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConnectors();
    void loadEvents();
    void loadNotes();
  }, [loadConnectors, loadEvents, loadNotes]);

  /** 留言：创建便签（mutation 可调即调）。 */
  async function createNote(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const content = noteText.trim();
    if (!content || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      await fetchCreateNote(content, false);
      setNoteText("");
      setMsg({ kind: "good", text: "留言已保存" });
      await loadNotes();
    } catch (err) {
      setMsg({ kind: "serious", text: errorMessageOf(err) });
    } finally {
      setBusy(false);
    }
  }

  const eventCols: ApiTableCol<BlackboardEvent>[] = [
    {
      key: "created_at",
      label: "时间",
      render: (ev) => <span className="text-xs text-text-secondary">{fmtAt(ev.created_at)}</span>,
    },
    {
      key: "by",
      label: "来源",
      render: (ev) => (
        <>
          {ev.by}
          <span className="text-xs text-text-secondary">（{ev.by_kind}）</span>
        </>
      ),
    },
    {
      key: "event_type",
      label: "事件类型",
      render: (ev) => (
        <span className="inline-flex rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text-secondary">
          {ev.event_type}
        </span>
      ),
    },
    {
      key: "payload_json",
      label: "内容",
      render: (ev) => (
        <span className="font-mono text-xs text-text-secondary" title={ev.payload_json}>
          {truncate(ev.payload_json, 60)}
        </span>
      ),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="连接器"
        desc="外部系统适配器诚实状态（未许可即 blocked）；黑板事件台账与便签留言"
        aside={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void loadConnectors();
              void loadEvents();
              void loadNotes();
            }}
          >
            刷新
          </Button>
        }
      />
      <ActionMsg msg={msg} />

      {/* ---- 连接器适配器（node-library.connectors） ---- */}
      <Section title="连接器适配器">
        {connErr ? (
          <ErrorState message={errorMessageOf(connErr)} onRetry={() => void loadConnectors()} />
        ) : !connectors ? (
          <p className="text-xs text-text-secondary">连接器状态加载中…</p>
        ) : Object.keys(connectors).length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 rounded-md border border-border bg-background py-6">
            <HedgehogMascot className="h-16 w-auto" />
            <p className="text-xs text-text-secondary">暂无连接器登记</p>
          </div>
        ) : (
          <div className="rounded-md border border-border bg-background px-3">
            {Object.entries(connectors).map(([name, c]) => (
              <div
                key={name}
                className="flex items-start justify-between gap-3 border-b border-border/60 py-2 last:border-0"
              >
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-text-primary">{name}</p>
                  <p className="mt-0.5 text-xs text-text-secondary">{c.reason}</p>
                  {!c.available && (
                    <p className="mt-1 text-xs text-text-secondary">
                      诚实状态：未许可（blocked）。启用前须完成许可评估与凭据隔离设计；
                      未启用期间不会执行任何外部调用。
                    </p>
                  )}
                </div>
                <StatusBadge kind={c.available ? "good" : "serious"}>
                  {c.available ? "可用" : "未许可"}
                </StatusBadge>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* ---- 黑板事件（append-only） ---- */}
      <Section title={`黑板事件（最近 ${eventsLoading ? "…" : events.length} 条）`}>
        {events401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <ApiTable
            rows={events}
            cols={eventCols}
            loading={eventsLoading}
            error={eventsErr}
            onRetry={() => void loadEvents()}
            emptyText="暂无黑板事件（append-only 台账）"
          />
        )}
      </Section>

      {/* ---- 便签留言 ---- */}
      <Section title={`便签留言（${notesLoading ? "…" : notes.length}）`}>
        {notes401 ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : notesErr ? (
          <ErrorState message={errorMessageOf(notesErr)} onRetry={() => void loadNotes()} />
        ) : (
          <div className="space-y-2">
            <form className="flex gap-2" onSubmit={(e) => void createNote(e)}>
              <Input
                value={noteText}
                placeholder="写一条留言，例如：今晚 8 点后不要跑训练任务"
                aria-label="留言内容"
                className="flex-1"
                onChange={(e) => setNoteText(e.target.value)}
              />
              <Button type="submit" size="sm" className="h-8" disabled={busy || !noteText.trim()}>
                发布留言
              </Button>
            </form>
            {notesLoading ? (
              <ApiTable rows={[]} cols={[{ key: "content", label: "留言" }]} loading />
            ) : notes.length === 0 ? (
              <div className="flex flex-col items-center gap-1.5 rounded-md border border-border bg-background py-6">
                <HedgehogMascot className="h-16 w-auto" />
                <p className="text-xs text-text-secondary">还没有留言，写第一条吧</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {notes.map((n) => (
                  <div key={n.note_id} className="rounded-md border border-border bg-background p-2.5">
                    <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-text-primary">
                      {n.content}
                    </p>
                    <p className="mt-1 text-xs text-text-secondary">
                      {n.actor} · {fmtAt(n.created_at)}
                      {n.pinned ? " · 置顶" : ""}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Section>
    </div>
  );
}
