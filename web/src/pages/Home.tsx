// ABOSV3 T2：首页 = 可运营总控 Dashboard（01 文档 §2）。
// 八类卡片全部来自真实 API（/api/v1/home/dashboard）：
// 今日待办 / 日历 / 项目进度 / 实时活动 / 系统容量 / Agent 提醒 /
// 快速目标 / 最近对象 + 服务端便签。点击卡片打开同一对象详情。
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  HealthBody, createCalendarEvent, createGoal, createNote,
  deleteCalendarEvent, deleteNote, fetchHomeDashboard,
  HomeCalendarEvent, HomeDashboard, HomeWorkItem,
} from "../api";
import { ModuleView, accentVar } from "../platform/registry";
import { EmptyState, ErrorState, Loading, StatusBadge } from
  "../platform/components";

// 同一对象详情跳转：不跳到无上下文的模块首页
function objectLink(refType: string, refId: string,
  subjectType?: string): string {
  switch (refType) {
    case "field_task": return "/geo/field";
    case "survey_assignment": return "/survey/field";
    case "bi_anomaly": return "/analytics/anomalies";
    case "work_item":
      if (subjectType === "recognition_task") return "/vision/tasks";
      if (subjectType === "workflow_run") return "/workflow/runs";
      return "/workflow/approvals";
    default:
      return refId ? `/workflow/runs` : "/home";
  }
}

const STATUS_CN: Record<string, string> = {
  todo: "待处理", running: "运行中", waiting: "等待人工",
  approval: "待批准", blocked: "阻断", done: "已完成",
  cancelled: "已取消",
};

export default function Home({ health, modules, identity }: {
  health: HealthBody | null;
  modules: ModuleView[];
  identity: { product_name_zh: string; definition: string } | null;
}) {
  const navigate = useNavigate();
  const [dash, setDash] = useState<HomeDashboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [goalBusy, setGoalBusy] = useState(false);
  const [goalErr, setGoalErr] = useState<string | null>(null);
  const [evTitle, setEvTitle] = useState("");
  const [evAt, setEvAt] = useState("");
  const [noteText, setNoteText] = useState("");

  const load = () => fetchHomeDashboard().then(setDash).catch(
    (e) => setErr(e instanceof Error ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  // 快速目标：先落服务端 goal_draft，再携 goal_id 打开主管（刷新可恢复）
  const handToSupervisor = async () => {
    const text = goal.trim();
    if (!text || goalBusy) return;
    setGoalBusy(true); setGoalErr(null);
    try {
      const g = await createGoal(text);
      setGoal("");
      navigate(`/home?focus=chat&goal=${encodeURIComponent(g.goal_id)}`);
    } catch (e) {
      setGoalErr(e instanceof Error ? e.message : String(e));
    } finally { setGoalBusy(false); }
  };

  const addEvent = async () => {
    if (!evTitle.trim() || !evAt) return;
    try {
      await createCalendarEvent({
        title: evTitle.trim(),
        starts_at: new Date(evAt).toISOString(),
      });
      setEvTitle(""); setEvAt(""); load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const addNote = async () => {
    if (!noteText.trim()) return;
    try {
      await createNote(noteText.trim());
      setNoteText(""); load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  if (err && !dash) {
    return <div className="page wide">
      <ErrorState message={`首页加载失败：${err}`}
        onRetry={() => { setErr(null); load(); }} /></div>;
  }
  if (!dash) return <div className="page wide">
    <Loading text="加载总控工作台…" /></div>;

  const open = dash.work_items.filter((w) =>
    ["todo", "running", "waiting", "approval", "blocked"].includes(
      w.status));
  const cap = dash.capacity;
  const fmtBytes = (b: number) => b > 2 ** 30
    ? `${(b / 2 ** 30).toFixed(1)} GB`
    : `${(b / 2 ** 20).toFixed(1)} MB`;

  return (
    <div className="page wide">
      <div className="page-header">
        <h1>{identity?.product_name_zh ?? "智能业务操作系统"} · 总控台</h1>
        <span className="desc">
          待办 / 日历 / 进度 / 活动 / 容量 / Agent 提醒 · 全部来自实时事实源
        </span>
      </div>

      {/* 快速目标（服务端持久化后交主管） */}
      <div className="card">
        <h3>快速目标（交给主管 Agent 拆解）</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ flex: 1 }} value={goal}
            aria-label="快速目标输入"
            placeholder="例如：导入这批客户地址 / 发布巡检问卷 / 识别这批照片…"
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handToSupervisor(); }} />
          <button className="btn primary"
            disabled={!goal.trim() || goalBusy}
            onClick={handToSupervisor}>
            {goalBusy ? "保存中…" : "交给主管"}</button>
        </div>
        {goalErr && <p className="v" style={{ color: "var(--err)" }}>
          目标保存失败：{goalErr}（目标必须落服务端，不静默丢失）</p>}
      </div>

      {err && <ErrorState message={err} onRetry={load} />}

      <div className="grid" style={{ gridTemplateColumns:
        "repeat(auto-fit, minmax(300px, 1fr))" }}>

        {/* 1. 今日待办（统一 current projection） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>今日待办（{open.length}）
            <span className="v" style={{ marginLeft: 8 }}>
              阻断 {dash.todos.blocked ?? 0} ·
              等待 {dash.todos.waiting ?? 0} ·
              运行 {dash.todos.running ?? 0}</span></h3>
          {open.length === 0
            ? <EmptyState title="当前没有未完成工作" />
            : open.slice(0, 8).map((w: HomeWorkItem) => (
              <Link key={w.work_id}
                to={objectLink("work_item", w.work_id, w.subject_type)}
                className={`note-card ${w.status === "blocked"
                  ? "blocked" : w.status === "waiting" || w.status
                    === "approval" ? "approval" : ""}`}>
                <div>{w.title || w.work_id}</div>
                <div className="meta">
                  {STATUS_CN[w.status] ?? w.status}
                  {w.owner_id ? ` · ${w.owner_id}` : ""}
                  {w.due_at ? ` · 截止 ${String(w.due_at).slice(0, 10)}`
                    : ""}
                  {w.blockers?.length
                    ? ` · ${String(w.blockers[0]).slice(0, 40)}` : ""}
                </div>
              </Link>))}
        </div>

        {/* 2. 日历（统一读取模型：用户日程+工作截止+外勤+问卷窗口） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>日历（{dash.calendar.length}）</h3>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <input style={{ flex: 1 }} placeholder="新日程标题"
              aria-label="新日程标题" value={evTitle}
              onChange={(e) => setEvTitle(e.target.value)} />
            <input type="datetime-local" aria-label="日程时间"
              value={evAt} onChange={(e) => setEvAt(e.target.value)} />
            <button className="btn" onClick={addEvent}
              disabled={!evTitle.trim() || !evAt}>添加</button>
          </div>
          {dash.calendar.length === 0
            ? <p className="v">暂无日程 · 诚实空态</p>
            : dash.calendar.slice(0, 8).map((ev: HomeCalendarEvent) => (
              <div key={ev.event_id} className="note-card"
                style={{ display: "flex", justifyContent: "space-between" }}>
                <div>
                  <div>{ev.title}</div>
                  <div className="meta">
                    {String(ev.when ?? ev.starts_at).slice(0, 16)
                      .replace("T", " ")}
                    · {ev.kind}
                    {ev.customer_id ? ` · ${ev.customer_id}` : ""}</div>
                </div>
                {ev.source === "user" && (
                  <button className="btn" aria-label="删除日程"
                    onClick={async () => {
                      await deleteCalendarEvent(ev.event_id); load();
                    }}>×</button>)}
              </div>))}
        </div>

        {/* 3. 项目进度（同一投影聚合） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>项目进度</h3>
          {dash.progress.projects.length === 0
            ? <p className="v">暂无归属项目的工作 · 诚实空态</p>
            : dash.progress.projects.slice(0, 6).map((p) => (
              <div key={p.project_id || p.customer_id || "na"}
                className="v" style={{ marginBottom: 8 }}>
                <div style={{ display: "flex",
                  justifyContent: "space-between" }}>
                  <span>{p.project_id || p.customer_id
                    || "（未归属）"}</span>
                  <span className="meta">
                    {p.done}/{p.total} · {p.completion}%</span>
                </div>
                <div style={{ height: 6, background: "var(--surface)",
                  borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${p.completion}%`, height: "100%",
                    background: "var(--ok, #3a9)" }} />
                </div>
                {(p.blocked > 0 || p.waiting > 0) && (
                  <div className="meta" style={{ color: "var(--warn)" }}>
                    阻断 {p.blocked} · 等待 {p.waiting}</div>)}
              </div>))}
          <p className="v"><Link to="/workflow/runs">运行概览：
            {Object.entries(dash.progress.runs_by_status).map(
              ([s, n]) => `${s} ${n}`).join(" · ") || "无运行"}</Link></p>
        </div>

        {/* 4. 实时活动（业务事件投影，无噪声） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>实时活动</h3>
          {dash.activity.length === 0
            ? <p className="v">暂无业务活动 · 诚实空态</p>
            : dash.activity.slice(0, 10).map((a) => (
              <div key={a.seq} className="v"
                style={{ marginBottom: 6 }}>
                <div>{a.text}
                  {a.subject_id ? <span className="meta">
                    {" "}· {a.subject_type}:
                    {String(a.subject_id).slice(0, 14)}…</span> : null}
                </div>
                <div className="meta">{String(a.at).slice(0, 19)
                  .replace("T", " ")} · {a.actor || "system"}
                  {a.error ? <span style={{ color: "var(--err)" }}>
                    {" "}· {a.error.slice(0, 60)}</span> : null}</div>
              </div>))}
        </div>

        {/* 5. 系统容量（真实读数） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>系统容量</h3>
          <p className="v">数据库：{fmtBytes(cap.db_bytes)} ·
            {" "}{cap.tables} 张表 · 迁移 {cap.migrations}</p>
          <p className="v">平台目录：{fmtBytes(cap.platform_dir_bytes)}
            {cap.disk?.free_gb !== undefined && (
              <> · 磁盘剩余 {cap.disk.free_gb} GB
                （共 {cap.disk.total_gb} GB）</>)}
          </p>
          <p className="v">Outbox 待投递：{cap.outbox_pending} ·
            队列：等待 {cap.jobs.queued ?? 0} /
            运行 {cap.jobs.running ?? 0} /
            失败 {cap.jobs.failed ?? 0}</p>
          <p className="v">服务：{health?.status ?? "未知"}
            <Link to="/status" style={{ marginLeft: 8 }}>
              系统状态 →</Link></p>
        </div>

        {/* 6. Agent 提醒（真实待批准/阻断/异常） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>Agent 提醒（{dash.agent_alerts.length}）</h3>
          {dash.agent_alerts.length === 0
            ? <p className="v">没有需要您决定的事项 · 诚实空态</p>
            : dash.agent_alerts.slice(0, 8).map((a, i) => (
              <Link key={i} to={objectLink(a.ref_type, a.ref_id)}
                className={`note-card ${a.kind === "blocked"
                  ? "blocked" : "approval"}`}>
                <div>{a.title}</div>
                <div className="meta">
                  {a.kind === "needs_decision" ? "需要决定"
                    : a.kind === "blocked" ? "被阻断" : "指标异常"}
                  {a.blockers?.length
                    ? ` · ${String(a.blockers[0]).slice(0, 50)}` : ""}
                </div>
              </Link>))}
        </div>

        {/* 7. 便签（服务端持久化，刷新不丢） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>便签（服务端保存）</h3>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <input style={{ flex: 1 }} value={noteText}
              aria-label="新便签内容" placeholder="记一条待办或备注…"
              onChange={(e) => setNoteText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addNote(); }} />
            <button className="btn" onClick={addNote}
              disabled={!noteText.trim()}>添加</button>
          </div>
          {dash.notes.length === 0
            ? <p className="v">暂无便签 · 诚实空态</p>
            : dash.notes.slice(0, 6).map((n) => (
              <div key={n.note_id} className="note-card"
                style={{ display: "flex",
                  justifyContent: "space-between" }}>
                <div>{n.pinned ? "📌 " : ""}{n.content}</div>
                <button className="btn" aria-label="删除便签"
                  onClick={async () => {
                    await deleteNote(n.note_id); load();
                  }}>×</button>
              </div>))}
        </div>

        {/* 8. 最近对象（点击直达同一对象） */}
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>最近对象</h3>
          {(["customers", "projects", "surveys", "workflows",
            "reports"] as const).map((k) => {
            const rows = dash.recent[k] ?? [];
            const route = k === "customers" ? "/master/customers"
              : k === "projects" ? "/master/projects"
                : k === "surveys" ? "/survey/design"
                  : k === "workflows" ? "/workflow/studio"
                    : "/analytics/reports";
            return rows.length === 0 ? null : (
              <div key={k} className="v" style={{ marginBottom: 6 }}>
                <div className="meta">{k}</div>
                {rows.slice(0, 3).map((r) => (
                  <Link key={String(r.id)} to={route}
                    style={{ marginRight: 10 }}>
                    {String(r.name ?? r.id).slice(0, 22)}
                    {r.status ? `（${r.status}）` : ""}</Link>))}
              </div>);
          })}
          <p className="v">
            <Link to="/vision/tasks">识别任务
              {" "}{dash.recent.recognition_tasks?.length ?? 0} 条 →</Link>
          </p>
        </div>
      </div>

      {/* 模块健康（Registry 实时投影） */}
      <div className="card" style={{ marginTop: 14 }}>
        <h3>模块健康（Registry 实时投影）</h3>
        {modules.length === 0
          ? <EmptyState title="模块注册表为空" />
          : (
            <table className="table">
              <thead><tr><th>模块</th><th>状态</th><th>Agent</th></tr></thead>
              <tbody>
                {modules.map((m) => (
                  <tr key={m.module_id}>
                    <td data-label="模块">
                      <span style={{ display: "inline-block",
                        width: 9, height: 9, borderRadius: 3,
                        background: accentVar(m.theme_token),
                        marginRight: 8 }} />
                      <Link to={m.navigation[0]?.route
                        ?? m.primary_route}>{m.name}</Link>
                    </td>
                    <td data-label="状态"><StatusBadge status={m.status} /></td>
                    <td data-label="Agent" className="v">
                      {m.agents.join("、") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  );
}
