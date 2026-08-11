// ABOS T9：首页 = 真实主管指挥中心。
// 待办/审批/运行/异常/完成/笔记/快速目标/模块健康全部来自
// Domain Service projection；无数据展示诚实空态，不硬编码数字。
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  HealthBody, createGoal, fetchRecognitionTasks, fetchRuns,
  fetchTaskboard, fetchWorkItems, WorkItemsBody,
} from "../api";
import { ModuleView, accentVar } from "../platform/registry";
import { EmptyState, ErrorState, Loading, StatusBadge } from
  "../platform/components";

export default function Home({ health, modules, identity }: {
  health: HealthBody | null;
  modules: ModuleView[];
  identity: { product_name_zh: string; definition: string } | null;
}) {
  const navigate = useNavigate();
  const [work, setWork] = useState<WorkItemsBody | null>(null);
  const [workErr, setWorkErr] = useState<string | null>(null);
  const [runs, setRuns] = useState<number | null>(null);
  const [tasks, setTasks] = useState<number | null>(null);
  const [board, setBoard] = useState<Record<string, any[]> | null>(null);
  const [goal, setGoal] = useState("");
  const [goalBusy, setGoalBusy] = useState(false);
  const [goalErr, setGoalErr] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkItems().then(setWork).catch(
      (e) => setWorkErr(e instanceof Error ? e.message : String(e)));
    fetchRuns().then((d) => setRuns(d.count)).catch(() => setRuns(null));
    fetchRecognitionTasks({ limit: 1 }).then(
      (d) => setTasks(d.count)).catch(() => setTasks(null));
    // ABOSV2-P0-001：任务板是较新的 cycle 投影，不得丢弃
    fetchTaskboard().then((d) => setBoard(d.states)).catch(
      () => setBoard(null));
  }, []);

  // ABOSV2-P0-002：目标先落服务端 goal_draft，再携带 goal_id 打开主管；
  // 不丢 URL 文本，不只存前端状态，刷新可从 open goals 恢复。
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

  const items = work?.items ?? [];
  const cols: Array<{ title: string; cls: string; filter: (i: any) => boolean }> = [
    { title: "今日待办", cls: "", filter: (i) =>
      i.kind.includes("todo") || i.stage === "todo" },
    { title: "需要批准", cls: "approval", filter: (i) =>
      i.kind.includes("approval") || i.stage === "approval" },
    { title: "正在运行", cls: "running", filter: (i) =>
      i.status === "active" || i.status === "running" },
    { title: "异常与告警", cls: "blocked", filter: (i) =>
      i.status === "blocked" || i.status_text?.includes("阻塞") },
    { title: "最近完成", cls: "", filter: (i) =>
      i.status === "done" || i.status === "completed" },
  ];

  return (
    <div className="page wide">
      <div className="page-header">
        <h1>{identity?.product_name_zh ?? "智能业务操作系统"} · 主管工作台</h1>
        <span className="desc">
          {identity?.definition?.slice(0, 60)}…</span>
      </div>

      <div className="card">
        <h3>快速目标（交给主管 Agent 拆解）</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ flex: 1 }} value={goal}
            aria-label="快速目标输入"
            placeholder="例如：用生产模型识别这批照片 / 打开识别任务…"
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

      {workErr && <ErrorState message={`工作项加载失败：${workErr}`}
        onRetry={() => { setWorkErr(null);
          fetchWorkItems().then(setWork).catch(
            (e) => setWorkErr(String(e))); }} />}
      {!work && !workErr && <Loading text="加载今日工作…" />}

      {work && (
        <div className="grid" style={{ gridTemplateColumns:
          "repeat(auto-fit, minmax(230px, 1fr))" }}>
          {cols.map((c) => {
            const list = items.filter(c.filter);
            return (
              <div className="card" key={c.title}
                style={{ marginBottom: 0 }}>
                <h3>{c.title}（{list.length}）</h3>
                {list.length === 0 ? (
                  <p className="v">暂无 · 诚实空态</p>
                ) : list.slice(0, 6).map((it) => (
                  <div key={it.id} className={`note-card ${c.cls}`}>
                    <div>{it.title}</div>
                    <div className="meta">{it.kind} · {it.status_text}</div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      <div className="grid" style={{ marginTop: 14 }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>运行概览（实时）</h3>
          <p className="v">Graph Runs：{runs === null ? "—" : runs} 条
            · 识别任务：{tasks === null ? "—" : tasks} 条
            · 服务：{health?.status ?? "未知"}
            {work?.summary?.superseded
              ? ` · 已归档历史待办 ${work.summary.superseded} 项` : ""}</p>
          {board && (
            <p className="v">
              周期任务板：等待 {board.waiting?.length ?? 0} ·
              运行 {board.running?.length ?? 0} ·
              待启动 {board.todo?.length ?? 0} ·
              完成 {board.done?.length ?? 0}
            </p>
          )}
          {board?.waiting?.slice(0, 3).map((s: any) => (
            <p key={s.logical_task_key} className="v"
              style={{ color: "var(--text-muted)" }}>
              · {s.title}：{s.blocker || "等待推进"}</p>
          ))}
          <p className="v">
            <Link to="/workflow/runs">查看 Graph Runs</Link> ·{" "}
            <Link to="/vision/tasks">查看识别任务</Link>
          </p>
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>模块健康（Registry 实时投影）</h3>
          {modules.length === 0
            ? <EmptyState title="模块注册表为空" />
            : (
              <table className="table">
                <thead><tr><th>模块</th><th>状态</th><th>Agent</th></tr></thead>
                <tbody>
                  {modules.map((m) => (
                    <tr key={m.module_id}>
                      <td>
                        <span style={{ display: "inline-block",
                          width: 9, height: 9, borderRadius: 3,
                          background: accentVar(m.theme_token),
                          marginRight: 8 }} />
                        <Link to={m.navigation[0]?.route
                          ?? m.primary_route}>{m.name}</Link>
                      </td>
                      <td><StatusBadge status={m.status} /></td>
                      <td className="v">{m.agents.join("、") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      </div>
    </div>
  );
}
