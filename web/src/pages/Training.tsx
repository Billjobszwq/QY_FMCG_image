import { ReactNode, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  TrainingGates,
  TrainingRunRow,
  approveTrainingPlan,
  dryRunTraining,
  enqueueTraining,
  fetchJobs,
  fetchMonitorLive,
  fetchMonitorOverview,
  fetchTrainingGates,
  fetchTrainingRuns,
  fetchTrainingSnapshots,
} from "../api";
import TrainingControlPanel from "./TrainingControl";

type Snap = Record<string, unknown>;
type Job = Record<string, unknown>;

// U2-4：训练/Job 状态统一业务语言
const TRAIN_STATUS_CN: Record<string, string> = {
  dry_run: "待批准",
  approved: "已批准",
  queued: "等待执行",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};
const JOB_STATUS_CN: Record<string, string> = {
  queued: "等待执行",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function cmdOf(r: TrainingRunRow): string {
  try {
    return JSON.stringify(JSON.parse(r.command_json), null, 1);
  } catch {
    return r.command_json;
  }
}

export default function Training() {
  const [live, setLive] = useState<Record<string, unknown> | null>(null);
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [gates, setGates] = useState<TrainingGates | null>(null);
  const [runs, setRuns] = useState<TrainingRunRow[] | null>(null);
  const [snaps, setSnaps] = useState<Snap[] | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [l, o, g, r, s, j] = await Promise.all([
        fetchMonitorLive().catch(() => null),
        fetchMonitorOverview().catch(() => null),
        fetchTrainingGates(),
        fetchTrainingRuns(),
        fetchTrainingSnapshots(),
        fetchJobs().catch(() => null),
      ]);
      setLive(l);
      setOverview(o);
      setGates(g);
      setRuns(r.runs);
      setSnaps(s.snapshots);
      setJobs(j ? j.jobs : null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // 活动 job 期间每 5s 轮询一次
  useEffect(() => {
    const active = (runs ?? []).some(
      (r) => r.status === "queued" || r.status === "running"
    );
    if (!active) return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [runs, reload]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const all = runs ?? [];
  const demoSnaps = (snaps ?? []).filter((s) => Number(s.trainable ?? 1) === 0);
  const okSnaps = (snaps ?? []).filter((s) => Number(s.trainable ?? 1) !== 0);
  const planRuns = all.filter((r) => r.kind === "dry_run");
  const approvedRuns = all.filter((r) => r.status === "approved");
  const activeRuns = all.filter(
    (r) => r.status === "queued" || r.status === "running"
  );
  const historyRuns = all.filter(
    (r) =>
      r.kind === "completed_candidate" ||
      ["completed", "failed", "cancelled"].includes(r.status)
  );
  const publishRuns = all.filter((r) => r.publish_status && r.publish_status !== "none");
  const activeJobs = (jobs ?? []).filter(
    (j) => j.kind === "training.run" && ["queued", "running"].includes(String(j.status))
  );

  const snapTable = (list: Snap[], demo: boolean) =>
    list.length === 0 ? (
      <p className="muted">无。</p>
    ) : (
      <table>
        <thead>
          <tr>
            <th>name@version</th>
            <th>mode</th>
            <th>manifest_hash</th>
            <th>来源审核</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {list.map((s) => (
            <tr key={String(s.snapshot_id)}>
              <td>
                {String(s.name)}@{String(s.version)}
              </td>
              <td>{String(s.mode)}</td>
              <td className="muted">{String(s.manifest_hash).slice(0, 12)}…</td>
              <td className="muted">
                {String(s.source_actor)}：{String(s.source_conclusion)}
              </td>
              <td>
                {demo ? (
                  <span className="pill pill-unavailable">不可训练（演示）</span>
                ) : (
                  <span
                    className={`pill pill-${s.status === "registered" ? "healthy" : "unavailable"}`}
                  >
                    {String(s.status)}
                  </span>
                )}
              </td>
              <td>
                {demo ? (
                  <span className="muted">仅展示，禁止训练</span>
                ) : (
                  <button
                    disabled={busy !== null || s.status !== "registered"}
                    onClick={() =>
                      act(`dry:${s.snapshot_id}`, () => dryRunTraining(String(s.snapshot_id)))
                    }
                  >
                    {busy === `dry:${s.snapshot_id}` ? "生成中…" : "dry-run"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );

  const runCard = (r: TrainingRunRow, actions: ReactNode) => (
    <div key={r.run_id} style={{ marginBottom: 12 }}>
      <p>
        <span className="muted">{r.run_id.slice(0, 8)}…</span>{" "}
        <span className={`pill pill-${r.status === "approved" ? "healthy" : "degraded"}`}>
          {TRAIN_STATUS_CN[r.status] ?? `${r.kind} / ${r.status}`}
        </span>{" "}
        <span className="pill pill-degraded">publish: {r.publish_status}</span>{" "}
        {r.approved_by && <span className="muted">批准人：{r.approved_by}</span>}
        {r.job_id && <span className="muted"> job: {r.job_id.slice(0, 8)}…</span>}
      </p>
      <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{cmdOf(r)}</pre>
      <p className="muted" style={{ fontSize: 12 }}>
        停止线：{r.stop_lines_json}
      </p>
      {actions}
    </div>
  );

  return (
    <>
      <TrainingControlPanel />
      <details style={{ marginTop: 24 }}>
        <summary>
          Legacy 训练治理区（单 YOLO snapshot 兼容层；8092
          旧监控只作只读参考，不再是统一进度事实源）
        </summary>
    <section>
      <h2>训练模型（M5 治理 · UMT 修正版）</h2>
      <p className="muted">
        模型 hot/warm/cold 驻留与 VLM 加载门禁请看
        <Link to="/models-runtime">模型驻留</Link>；Qwen3-VL
        训练在当前 YOLO 训练运行期间全部保持
        BLOCKED_BY_ACTIVE_TRAINING，仅允许 mock/parse-only 测试。
      </p>
      {error && <div className="banner banner-unavailable">错误：{error}</div>}
      {gates && (
        <div className={`banner ${gates.can_train ? "banner-healthy" : "banner-degraded"}`}>
          {gates.training_authorized
            ? "training_authorized=true：训练已获显式授权（批准计划与提交 Job 为两步独立操作）。"
            : "当前无训练授权：training_started=false。平台不消耗算力。"}
          {!gates.can_train && gates.reasons.length > 0 && (
            <ul style={{ margin: "6px 0 0" }}>
              {gates.reasons.map((r) => (
                <li key={r}>为什么不能训练：{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <h3>① 演示快照（不可训练）</h3>
      {snaps === null ? <p className="muted">加载中…</p> : snapTable(demoSnaps, true)}

      <h3>② 可训练快照（服务端 builder 生成，split guard 通过）</h3>
      {snaps === null ? (
        <p className="muted">加载中…</p>
      ) : okSnaps.length === 0 ? (
        <p className="muted">暂无可训练快照。须经服务端 builder 注册（train/val 门店/session/sha 零交集守卫）。</p>
      ) : (
        snapTable(okSnaps, false)
      )}

      <h3>③ 训练计划（dry-run：命令 / MPS G0 / 预算 / 停止线）</h3>
      {runs === null ? (
        <p className="muted">加载中…</p>
      ) : planRuns.length === 0 ? (
        <p className="muted">暂无计划。对可训练快照执行 dry-run 生成（需登录）。</p>
      ) : (
        planRuns.map((r) =>
          runCard(
            r,
            <button
              disabled={busy !== null}
              onClick={() => act(`approve:${r.run_id}`, () => approveTrainingPlan(r.run_id))}
            >
              {busy === `approve:${r.run_id}` ? "批准中…" : "批准训练计划"}
            </button>
          )
        )
      )}

      <h3>④ 已批准计划（待提交训练 Job）</h3>
      {runs === null ? (
        <p className="muted">加载中…</p>
      ) : approvedRuns.length === 0 ? (
        <p className="muted">无已批准待提交的计划。</p>
      ) : (
        approvedRuns.map((r) =>
          runCard(
            r,
            <button
              disabled={busy !== null}
              onClick={() => act(`enqueue:${r.run_id}`, () => enqueueTraining(r.run_id))}
            >
              {busy === `enqueue:${r.run_id}` ? "提交中…" : "提交训练 Job"}
            </button>
          )
        )
      )}

      <h3>⑤ 活动训练 Job</h3>
      {activeRuns.length === 0 && activeJobs.length === 0 ? (
        <div className="banner banner-degraded">idle：当前无活动训练 Job，平台未消耗训练算力。</div>
      ) : (
        <>
          {activeRuns.map((r) => (
            <p key={r.run_id}>
              <span className="muted">{r.run_id.slice(0, 8)}…</span>{" "}
              <span className="pill pill-healthy">{TRAIN_STATUS_CN[r.status] ?? r.status}</span>{" "}
              {r.job_id && <span className="muted">job: {r.job_id.slice(0, 8)}…</span>}
            </p>
          ))}
          {activeJobs.map((j) => (
            <p key={String(j.job_id)}>
              <span className="muted">job {String(j.job_id).slice(0, 8)}…</span>{" "}
              <span className="pill pill-healthy">{JOB_STATUS_CN[String(j.status)] ?? String(j.status)}</span>{" "}
              <span className="muted">attempt {String(j.attempt_no ?? "?")}</span>
            </p>
          ))}
        </>
      )}

      <h3>⑥ 历史实验</h3>
      {runs === null ? (
        <p className="muted">加载中…</p>
      ) : historyRuns.length === 0 ? (
        <p className="muted">无历史实验记录。</p>
      ) : (
        historyRuns.map((r) => runCard(r, null))
      )}

      <h3>⑦ 生产模型（独立发布审批）</h3>
      {runs === null ? (
        <p className="muted">加载中…</p>
      ) : publishRuns.length === 0 ? (
        <p className="muted">无发布流程。训练完成只产生 candidate，发布需独立 admin 审批。</p>
      ) : (
        publishRuns.map((r) => (
          <p key={r.run_id}>
            <span className="muted">{r.run_id.slice(0, 8)}…</span>{" "}
            <span className="pill pill-degraded">publish: {r.publish_status}</span>
          </p>
        ))
      )}

      <h3>8092 监控（只读，旧链路）</h3>
      {!live && !overview && <p className="muted">监控不可用或加载中…</p>}
      {live && (
        <div className="cards">
          <div className="card">
            <div className="k">分类器</div>
            <div className="v sm">
              {String(live.backbone ?? "—")} ep{String(live.epoch ?? "?")}/{String(live.total_epochs ?? "?")}
            </div>
          </div>
          <div className="card">
            <div className="k">best acc</div>
            <div className="v sm">{((Number(live.best_acc) || 0) * 100).toFixed(2)}%</div>
          </div>
          <div className="card">
            <div className="k">阶段</div>
            <div className="v sm">{String(live.phase ?? "—")}</div>
          </div>
        </div>
      )}
      {((overview?.yolo_runs as Array<Record<string, unknown>> | undefined) ?? []).length > 0 && (
        <table>
          <thead>
            <tr>
              <th>run</th>
              <th>epochs</th>
            </tr>
          </thead>
          <tbody>
            {((overview?.yolo_runs as Array<Record<string, unknown>> | undefined) ?? []).map((r) => (
              <tr key={String(r.run)}>
                <td>{String(r.run)}</td>
                <td>{Array.isArray(r.epochs) ? r.epochs.length : 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        红线：写操作需本机登录 + CSRF；批准计划与提交 Job 为两步；训练完成只产生 candidate，不自动发布；
        旧 /retrain auto_switch=true 不进新平台。
      </p>
    </section>
      </details>
    </>
  );
}
