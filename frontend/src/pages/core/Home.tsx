/**
 * 首页 · 总控台（P1 core/Home）。
 *
 * 数据源（全部同源 /api/v1/*，禁止样本数据）：
 * —— /api/v1/home/dashboard：待办 / 日历 / 进度 / 活动 / 容量 / Agent 提醒 /
 *    最近对象 / 便签（需登录会话，401 → NeedLoginState）；
 * —— /api/v1/health：整体健康与服务计数；
 * —— /api/v1/monitor/overview：训练监控要点（best_yolo / classifier / services）。
 *
 * 关键操作（真实 mutation，失败 serious 徽章提示）：
 * —— 快速目标 → POST /api/v1/goals（落服务端，不静默丢失）；
 * —— 便签新增 / 删除、日程新增 / 删除。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  fetchCreateCalendarEvent,
  fetchCreateGoal,
  fetchCreateNote,
  fetchDeleteCalendarEvent,
  fetchDeleteNote,
  fetchHealth,
  fetchHomeDashboard,
  fetchMonitorOverview,
} from "@/lib/api";
import type { HealthBody, HomeDashboard, ServiceStatus } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useWindowManager } from "@/store/windowStore";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HedgehogLoader } from "@/components/ui/loader";
import { HedgehogMascot } from "@/components/ui/mascot";
import { StatTile } from "@/components/charts/primitives";
import {
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
} from "@/components/data";
import type { StatusKind } from "@/components/data";
import { cn } from "@/lib/utils";

/* ============================================================================
   本地小件（卡片壳 / 空态 / 格式化）
   ========================================================================== */

/** 细边框小圆角卡片壳：标题行 + 内容区。 */
function Card({
  title,
  aside,
  children,
  className,
}: {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-md border border-border bg-background", className)}>
      {title && (
        <header className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
          <h3 className="font-display text-[13px] font-bold text-text-primary">
            {title}
          </h3>
          {aside}
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}

/** 卡片内诚实空态：小刺猬 + 一句话。 */
function MiniEmpty({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-1 py-3">
      <HedgehogMascot className="h-14 w-auto" />
      <p className="text-xs text-text-secondary">{text}</p>
    </div>
  );
}

/** 服务端 UTC ISO → 本地时间展示（不得直接显示 UTC）。 */
function fmtWhen(s?: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return String(s).slice(0, 16);
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}`
  );
}

/** 字节数人类可读。 */
function fmtBytes(b: number): string {
  return b > 2 ** 30
    ? `${(b / 2 ** 30).toFixed(1)} GB`
    : `${(b / 2 ** 20).toFixed(1)} MB`;
}

/** 工作状态 → StatusBadge（图标 + 文字，全局唯一状态呈现）。 */
const WORK_STATUS_CN: Record<string, { kind: StatusKind; label: string }> = {
  todo: { kind: "neutral", label: "待处理" },
  running: { kind: "good", label: "运行中" },
  waiting: { kind: "warn", label: "等待人工" },
  approval: { kind: "warn", label: "待批准" },
  blocked: { kind: "serious", label: "阻断" },
  done: { kind: "good", label: "已完成" },
  cancelled: { kind: "neutral", label: "已取消" },
};

function WorkStatusBadge({ status }: { status: string }) {
  const m = WORK_STATUS_CN[status] ?? { kind: "neutral" as const, label: status };
  return <StatusBadge kind={m.kind}>{m.label}</StatusBadge>;
}

/** 健康状态 → StatusBadge。 */
function healthKind(status: string | undefined): StatusKind {
  if (status === "healthy") return "good";
  if (status === "degraded") return "warn";
  if (status === "unavailable") return "serious";
  return "neutral";
}

const HEALTH_CN: Record<string, string> = {
  healthy: "正常",
  degraded: "降级",
  unavailable: "不可用",
};

/** monitor/overview 弹性载荷：只做防御式取值。 */
interface MonitorOverviewLike {
  best_yolo?: { run?: string; map50?: number; epoch?: number } | null;
  classifier?: {
    best_acc?: number | null;
    best_epoch?: number | null;
    finished?: boolean;
    active?: boolean;
  } | null;
  services?: Record<string, string>;
  processes?: Record<string, boolean>;
  yolo_runs?: unknown[];
}

const OPEN_STATUSES = ["todo", "running", "waiting", "approval", "blocked"];

/* ============================================================================
   页面
   ========================================================================== */

export default function Home() {
  const me = useAuth((s) => s.me);
  const openWindow = useWindowManager((s) => s.openWindow);
  const closeWindow = useWindowManager((s) => s.closeWindow);

  const [dash, setDash] = useState<HomeDashboard | null>(null);
  const [health, setHealth] = useState<HealthBody | null>(null);
  const [monitor, setMonitor] = useState<MonitorOverviewLike | null>(null);
  const [dashErr, setDashErr] = useState<unknown>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [healthErr, setHealthErr] = useState<unknown>(null);
  const [monitorErr, setMonitorErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  // 快速目标 / 便签 / 日程的输入与失败提示
  const [goal, setGoal] = useState("");
  const [goalBusy, setGoalBusy] = useState(false);
  const [goalErr, setGoalErr] = useState<string | null>(null);
  const [goalSaved, setGoalSaved] = useState<string | null>(null);
  const [noteText, setNoteText] = useState("");
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const [evTitle, setEvTitle] = useState("");
  const [evAt, setEvAt] = useState("");
  const [evErr, setEvErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setDashErr(null);
    setHealthErr(null);
    setMonitorErr(null);
    const [d, h, m] = await Promise.allSettled([
      fetchHomeDashboard(),
      fetchHealth(),
      fetchMonitorOverview(),
    ]);
    if (d.status === "fulfilled") {
      setDash(d.value);
      setNeedLogin(false);
    } else {
      setDash(null);
      setDashErr(d.reason);
      setNeedLogin(d.reason instanceof ApiError && d.reason.status === 401);
    }
    if (h.status === "fulfilled") setHealth(h.value);
    else {
      setHealth(null);
      setHealthErr(h.reason);
    }
    if (m.status === "fulfilled") setMonitor(m.value as MonitorOverviewLike);
    else {
      setMonitor(null);
      setMonitorErr(m.reason);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 登录成功后自动重试被 401 拦下的数据
  useEffect(() => {
    if (me && needLogin) void load();
  }, [me, needLogin, load]);

  /** 打开登录窗口（桌面层窗口管理器承载）。 */
  const openLoginWindow = useCallback(() => {
    openWindow({
      id: "login",
      title: "平台登录",
      content: <LoginWindow onLoggedIn={() => closeWindow("login")} />,
      defaultPosition: {
        x: Math.max(16, window.innerWidth / 2 - 180),
        y: 120,
      },
      defaultSize: { width: 360, height: 460 },
      resizable: false,
    });
  }, [openWindow, closeWindow]);

  /* ---- 关键操作（真实 mutation） ---- */

  const handToSupervisor = async () => {
    const text = goal.trim();
    if (!text || goalBusy) return;
    setGoalBusy(true);
    setGoalErr(null);
    setGoalSaved(null);
    try {
      const g = await fetchCreateGoal(text);
      setGoal("");
      setGoalSaved(`目标已保存（${g.goal_id}），等待主管 Agent 拆解`);
    } catch (e) {
      setGoalErr(e instanceof Error ? e.message : "保存失败");
    } finally {
      setGoalBusy(false);
    }
  };

  const addNote = async () => {
    const text = noteText.trim();
    if (!text) return;
    setNoteErr(null);
    try {
      await fetchCreateNote(text);
      setNoteText("");
      void load();
    } catch (e) {
      setNoteErr(e instanceof Error ? e.message : "保存失败");
    }
  };

  const removeNote = async (noteId: string) => {
    setNoteErr(null);
    try {
      await fetchDeleteNote(noteId);
      void load();
    } catch (e) {
      setNoteErr(e instanceof Error ? e.message : "删除失败");
    }
  };

  const addEvent = async () => {
    if (!evTitle.trim() || !evAt) return;
    setEvErr(null);
    try {
      await fetchCreateCalendarEvent({
        title: evTitle.trim(),
        starts_at: new Date(evAt).toISOString(),
      });
      setEvTitle("");
      setEvAt("");
      void load();
    } catch (e) {
      setEvErr(e instanceof Error ? e.message : "保存失败");
    }
  };

  const removeEvent = async (eventId: string) => {
    setEvErr(null);
    try {
      await fetchDeleteCalendarEvent(eventId);
      void load();
    } catch (e) {
      setEvErr(e instanceof Error ? e.message : "删除失败");
    }
  };

  /* ---- 渲染 ---- */

  const header = (
    <PageHeader
      title="总控台"
      desc="待办 / 日历 / 进度 / 活动 / 容量 / Agent 提醒 · 全部来自实时事实源"
      aside={
        <>
          <StatusBadge kind={healthKind(health?.status)}>
            服务 {HEALTH_CN[health?.status ?? ""] ?? health?.status ?? "未知"}
          </StatusBadge>
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            刷新
          </Button>
        </>
      }
    />
  );

  // 401：需要登录（数据红线）
  if (needLogin) {
    return (
      <div className="p-5 space-y-4">
        {header}
        <NeedLoginState onOpenLogin={openLoginWindow} />
      </div>
    );
  }

  // 首屏加载失败：错误态 + 重试
  if (dashErr && !dash) {
    return (
      <div className="p-5 space-y-4">
        {header}
        <ErrorState
          message={dashErr instanceof Error ? dashErr.message : undefined}
          onRetry={() => void load()}
        />
      </div>
    );
  }

  // 首屏加载中：刺猬（禁通用旋转圈）
  if (loading && !dash) {
    return (
      <div className="p-5 space-y-4">
        {header}
        <div className="flex flex-col items-center gap-2 py-16">
          <HedgehogLoader className="h-10 w-auto" />
          <p className="text-xs text-text-secondary">加载总控工作台…</p>
        </div>
      </div>
    );
  }

  if (!dash) return <div className="p-5 space-y-4">{header}</div>;

  const open = dash.work_items.filter((w) => OPEN_STATUSES.includes(w.status));
  const cap = dash.capacity;
  const todos = dash.todos;

  const servicesUp = monitor
    ? Object.values(monitor.services ?? {}).filter((s) => s === "up").length
    : 0;
  const servicesTotal = monitor
    ? Object.keys(monitor.services ?? {}).length
    : 0;
  const downNames = monitor
    ? Object.entries(monitor.services ?? {})
        .filter(([, s]) => s !== "up")
        .map(([n]) => n)
    : [];

  return (
    <div className="p-5 space-y-4">
      {header}

      {/* 快速目标：先落服务端 goal_draft，再提示等待主管拆解 */}
      <Card title="快速目标（交给主管 Agent 拆解）">
        <div className="flex flex-wrap gap-2">
          <Input
            className="min-w-56 flex-1"
            value={goal}
            aria-label="快速目标输入"
            placeholder="例如：导入这批客户地址 / 发布巡检问卷 / 识别这批照片…"
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void handToSupervisor();
            }}
          />
          <Button
            size="sm"
            className="h-8"
            disabled={!goal.trim() || goalBusy}
            onClick={() => void handToSupervisor()}
          >
            {goalBusy ? "保存中…" : "交给主管"}
          </Button>
        </div>
        {goalErr && (
          <div className="mt-2">
            <StatusBadge kind="serious">
              目标保存失败：{goalErr}（目标必须落服务端，不静默丢失）
            </StatusBadge>
          </div>
        )}
        {goalSaved && (
          <p className="mt-2 text-xs text-text-secondary">{goalSaved}</p>
        )}
      </Card>

      {/* KPI 行（真实读数，禁止硬编码数字） */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile
          label="未完成工作"
          value={open.length}
          note={`台账共 ${dash.progress.work_total} 条`}
        />
        <StatTile label="待处理" value={todos.todo ?? 0} note="等待认领启动" />
        <StatTile label="运行中" value={todos.running ?? 0} note="Agent / 工作流执行" />
        <StatTile
          label="等待人工"
          value={(todos.waiting ?? 0) + (todos.approval ?? 0)}
          note="等待确认或批准"
        />
        <StatTile label="阻断" value={todos.blocked ?? 0} note="需要先解除阻断" />
        <StatTile
          label="Agent 提醒"
          value={dash.agent_alerts.length}
          note="需要您决定的事项"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {/* 今日待办 */}
        <Card title={`今日待办（${open.length}）`}>
          {open.length === 0 ? (
            <MiniEmpty text="当前没有未完成工作" />
          ) : (
            <ul className="space-y-1.5">
              {open.slice(0, 8).map((w) => (
                <li
                  key={w.work_id}
                  className="rounded-md border border-border/60 bg-surface px-2.5 py-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] text-text-primary">
                      {w.title || w.work_id}
                    </span>
                    <WorkStatusBadge status={w.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {w.owner_id ? `${w.owner_id}` : "未分配"}
                    {w.due_at ? ` · 截止 ${fmtWhen(w.due_at).slice(0, 10)}` : ""}
                    {w.blockers?.length ? " · 有阻断（详情见工作项）" : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Agent 提醒 */}
        <Card title={`Agent 提醒（${dash.agent_alerts.length}）`}>
          {dash.agent_alerts.length === 0 ? (
            <MiniEmpty text="没有需要您决定的事项" />
          ) : (
            <ul className="space-y-1.5">
              {dash.agent_alerts.slice(0, 8).map((a, i) => (
                <li
                  key={`${a.ref_type}-${a.ref_id}-${i}`}
                  className="rounded-md border border-border/60 bg-surface px-2.5 py-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] text-text-primary">
                      {a.title}
                    </span>
                    <StatusBadge
                      kind={a.kind === "blocked" ? "serious" : "warn"}
                    >
                      {a.kind === "needs_decision"
                        ? "需要决定"
                        : a.kind === "blocked"
                          ? "被阻断"
                          : "指标异常"}
                    </StatusBadge>
                  </div>
                  {a.blockers?.length ? (
                    <p className="mt-0.5 text-xs text-text-secondary">
                      阻断原因见详情
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* 日历 */}
        <Card title={`日历（${dash.calendar.length}）`}>
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Input
              className="min-w-32 flex-1"
              placeholder="新日程标题"
              aria-label="新日程标题"
              value={evTitle}
              onChange={(e) => setEvTitle(e.target.value)}
            />
            <Input
              type="datetime-local"
              className="w-auto"
              aria-label="日程时间"
              value={evAt}
              onChange={(e) => setEvAt(e.target.value)}
            />
            <Button
              variant="secondary"
              size="sm"
              className="h-8"
              disabled={!evTitle.trim() || !evAt}
              onClick={() => void addEvent()}
            >
              添加
            </Button>
          </div>
          {evErr && (
            <div className="mb-2">
              <StatusBadge kind="serious">{evErr}</StatusBadge>
            </div>
          )}
          {dash.calendar.length === 0 ? (
            <MiniEmpty text="暂无日程" />
          ) : (
            <ul className="space-y-1.5">
              {dash.calendar.slice(0, 8).map((ev) => (
                <li
                  key={ev.event_id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border/60 bg-surface px-2.5 py-1.5"
                >
                  <div className="min-w-0">
                    <div className="truncate text-[13px] text-text-primary">
                      {ev.title}
                    </div>
                    <div className="text-xs text-text-secondary">
                      {fmtWhen(ev.when ?? ev.starts_at)} · {ev.kind}
                      {ev.customer_id ? ` · ${ev.customer_id}` : ""}
                    </div>
                  </div>
                  {ev.source === "user" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-1.5"
                      aria-label="删除日程"
                      onClick={() => void removeEvent(ev.event_id)}
                    >
                      删除
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* 项目进度 */}
        <Card title="项目进度">
          {dash.progress.projects.length === 0 ? (
            <MiniEmpty text="暂无归属项目的工作" />
          ) : (
            <ul className="space-y-2.5">
              {dash.progress.projects.slice(0, 6).map((p) => (
                <li key={p.project_id || p.customer_id || "na"}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[13px] text-text-primary">
                      {p.project_id || p.customer_id || "（未归属）"}
                    </span>
                    <span className="text-xs text-text-secondary tabular-nums">
                      {p.done}/{p.total} · {p.completion}%
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, Math.max(0, p.completion))}%`,
                        background: "var(--color-series-1)",
                      }}
                    />
                  </div>
                  {(p.blocked > 0 || p.waiting > 0) && (
                    <div className="mt-1 flex gap-1.5">
                      {p.blocked > 0 && (
                        <StatusBadge kind="serious">阻断 {p.blocked}</StatusBadge>
                      )}
                      {p.waiting > 0 && (
                        <StatusBadge kind="warn">等待 {p.waiting}</StatusBadge>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 border-t border-border/60 pt-2 text-xs text-text-secondary">
            运行概览：
            {Object.entries(dash.progress.runs_by_status)
              .map(([s, n]) => `${s} ${n}`)
              .join(" · ") || "无运行"}
          </p>
        </Card>

        {/* 实时活动 */}
        <Card title="实时活动">
          {dash.activity.length === 0 ? (
            <MiniEmpty text="暂无业务活动" />
          ) : (
            <ul className="space-y-1.5">
              {dash.activity.slice(0, 10).map((a) => (
                <li key={a.seq}>
                  <p className="text-[13px] leading-snug text-text-primary">
                    {a.text}
                    {a.subject_id ? (
                      <span className="text-xs text-text-secondary">
                        {" "}
                        · {a.subject_type}:{String(a.subject_id).slice(0, 14)}…
                      </span>
                    ) : null}
                  </p>
                  <p className="text-xs text-text-secondary">
                    {fmtWhen(a.at)} · {a.actor || "system"}
                    {a.error ? (
                      <StatusBadge kind="serious" className="ml-1.5">
                        运行失败（详情见运行记录）
                      </StatusBadge>
                    ) : null}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* 系统容量（真实读数） */}
        <Card title="系统容量">
          <dl className="space-y-1.5 text-[13px]">
            {(
              [
                [
                  "数据库",
                  `${fmtBytes(cap.db_bytes)} · ${cap.tables} 张表 · 迁移 ${cap.migrations}`,
                ],
                [
                  "平台目录",
                  `${fmtBytes(cap.platform_dir_bytes)}${
                    cap.disk?.free_gb !== undefined
                      ? ` · 磁盘剩余 ${cap.disk.free_gb} GB（共 ${cap.disk.total_gb} GB）`
                      : ""
                  }`,
                ],
                [
                  "投递与队列",
                  `Outbox 待投递 ${cap.outbox_pending} · 等待 ${cap.jobs.queued ?? 0} / 运行 ${cap.jobs.running ?? 0} / 失败 ${cap.jobs.failed ?? 0}`,
                ],
              ] as const
            ).map(([label, value]) => (
              <div
                key={label}
                className="grid grid-cols-[88px_1fr] items-baseline gap-x-3 border-b border-border/60 pb-1.5 last:border-0 last:pb-0"
              >
                <dt className="text-xs text-text-secondary">{label}</dt>
                <dd className="text-text-primary">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-2 border-t border-border/60 pt-2">
            {healthErr ? (
              <ErrorState
                className="py-2"
                message={healthErr instanceof Error ? healthErr.message : undefined}
                onRetry={() => void load()}
              />
            ) : health ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <StatusBadge kind={healthKind(health.status)}>
                  服务整体{HEALTH_CN[health.status] ?? health.status}
                </StatusBadge>
                {(
                  ["healthy", "degraded", "unavailable"] as const
                ).map((s) => {
                  const n = health.services.filter(
                    (x: ServiceStatus) => x.status === s,
                  ).length;
                  return n > 0 ? (
                    <span key={s} className="text-xs text-text-secondary">
                      {HEALTH_CN[s]} {n}
                    </span>
                  ) : null;
                })}
                <span className="text-xs text-text-secondary">
                  · 详见「系统状态」
                </span>
              </div>
            ) : (
              <p className="text-xs text-text-secondary">健康数据暂缺</p>
            )}
          </div>
        </Card>

        {/* 训练监控（monitor/overview） */}
        <Card title="训练监控">
          {monitorErr ? (
            <ErrorState
              className="py-2"
              message={
                monitorErr instanceof Error ? monitorErr.message : undefined
              }
              onRetry={() => void load()}
            />
          ) : monitor ? (
            <div className="space-y-1.5 text-[13px] text-text-primary">
              {monitor.best_yolo ? (
                <p>
                  最佳 YOLO：{monitor.best_yolo.run ?? "—"} · mAP50{" "}
                  <span className="tabular-nums">
                    {monitor.best_yolo.map50}
                  </span>
                  {monitor.best_yolo.epoch !== undefined
                    ? ` @ ep${monitor.best_yolo.epoch}`
                    : ""}
                </p>
              ) : (
                <p className="text-text-secondary">暂无 YOLO 训练记录</p>
              )}
              {monitor.classifier?.best_acc != null ? (
                <p>
                  分类器最佳 val_acc{" "}
                  <span className="tabular-nums">
                    {monitor.classifier.best_acc}
                  </span>
                  {monitor.classifier.best_epoch != null
                    ? ` @ ep${monitor.classifier.best_epoch}`
                    : ""}
                  {monitor.classifier.finished ? " · 训练已结束" : ""}
                </p>
              ) : (
                <p className="text-text-secondary">暂无分类器训练记录</p>
              )}
              <p>
                监控服务：{servicesUp}/{servicesTotal} 在线
                {downNames.length > 0 ? (
                  <StatusBadge kind="warn" className="ml-1.5">
                    离线 {downNames.join("、")}
                  </StatusBadge>
                ) : (
                  <StatusBadge kind="good" className="ml-1.5">
                    全部在线
                  </StatusBadge>
                )}
              </p>
              <p className="text-xs text-text-secondary">
                训练进程：YOLO{" "}
                {monitor.processes?.yolo_training ? "运行中" : "空闲"} · 分类器{" "}
                {monitor.processes?.classifier_training ? "运行中" : "空闲"} ·
                历史训练 {monitor.yolo_runs?.length ?? 0} 条
              </p>
            </div>
          ) : (
            <p className="text-xs text-text-secondary">监控数据暂缺</p>
          )}
        </Card>

        {/* 便签（服务端保存） */}
        <Card title="便签（服务端保存）">
          <div className="mb-2 flex gap-1.5">
            <Input
              className="flex-1"
              value={noteText}
              aria-label="新便签内容"
              placeholder="记一条待办或备注…"
              onChange={(e) => setNoteText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void addNote();
              }}
            />
            <Button
              variant="secondary"
              size="sm"
              className="h-8"
              disabled={!noteText.trim()}
              onClick={() => void addNote()}
            >
              添加
            </Button>
          </div>
          {noteErr && (
            <div className="mb-2">
              <StatusBadge kind="serious">{noteErr}</StatusBadge>
            </div>
          )}
          {dash.notes.length === 0 ? (
            <MiniEmpty text="暂无便签" />
          ) : (
            <ul className="space-y-1.5">
              {dash.notes.slice(0, 6).map((n) => (
                <li
                  key={n.note_id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border/60 bg-surface px-2.5 py-1.5"
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                    {n.pinned ? (
                      <StatusBadge kind="neutral">置顶</StatusBadge>
                    ) : null}
                    <span className="truncate text-[13px] text-text-primary">
                      {n.content}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 shrink-0 px-1.5"
                    aria-label="删除便签"
                    onClick={() => void removeNote(n.note_id)}
                  >
                    删除
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* 最近对象 */}
        <Card title="最近对象" className="md:col-span-2 xl:col-span-1">
          {(() => {
            const groups = (
              [
                ["customers", "客户"],
                ["projects", "项目"],
                ["surveys", "问卷"],
                ["workflows", "工作流"],
                ["reports", "报表"],
              ] as const
            )
              .map(([k, label]) => ({
                label,
                rows: dash.recent[k] ?? [],
              }))
              .filter((g) => g.rows.length > 0);
            if (groups.length === 0 && !dash.recent.recognition_tasks?.length) {
              return <MiniEmpty text="暂无最近对象" />;
            }
            return (
              <div className="space-y-2">
                {groups.map((g) => (
                  <div key={g.label}>
                    <p className="text-xs text-text-secondary">{g.label}</p>
                    <p className="text-[13px] text-text-primary">
                      {g.rows
                        .slice(0, 3)
                        .map((r) => {
                          const name = String(r.name ?? r.id ?? "—").slice(0, 22);
                          return r.status ? `${name}（${r.status}）` : name;
                        })
                        .join(" · ")}
                    </p>
                  </div>
                ))}
                <p className="border-t border-border/60 pt-2 text-xs text-text-secondary">
                  识别任务 {dash.recent.recognition_tasks?.length ?? 0} 条 ·
                  详见「识别任务」
                </p>
              </div>
            );
          })()}
        </Card>
      </div>
    </div>
  );
}
