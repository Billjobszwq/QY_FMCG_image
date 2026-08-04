import { useCallback, useEffect, useState } from "react";
import {
  TrainingGates,
  TrainingRunRow,
  dryRunTraining,
  fetchMonitorLive,
  fetchMonitorOverview,
  fetchTrainingGates,
  fetchTrainingRuns,
  fetchTrainingSnapshots,
} from "../api";

export default function Training() {
  const [live, setLive] = useState<Record<string, unknown> | null>(null);
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [gates, setGates] = useState<TrainingGates | null>(null);
  const [runs, setRuns] = useState<TrainingRunRow[] | null>(null);
  const [snaps, setSnaps] = useState<Array<Record<string, unknown>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [l, o, g, r, s] = await Promise.all([
        fetchMonitorLive().catch(() => null),
        fetchMonitorOverview().catch(() => null),
        fetchTrainingGates(),
        fetchTrainingRuns(),
        fetchTrainingSnapshots(),
      ]);
      setLive(l);
      setOverview(o);
      setGates(g);
      setRuns(r.runs);
      setSnaps(s.snapshots);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const onDryRun = async (snapshotId: string) => {
    setBusy(true);
    try {
      await dryRunTraining(snapshotId);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const legacyRuns = (overview?.yolo_runs as Array<Record<string, unknown>> | undefined) ?? [];

  return (
    <section>
      <h2>训练模型（M5 治理）</h2>
      {error && <div className="banner banner-unavailable">错误：{error}</div>}
      {gates && (
        <div className={`banner ${gates.can_train ? "banner-healthy" : "banner-degraded"}`}>
          {gates.training_authorized
            ? "training_authorized=true：训练已获显式授权（平台仍不自动执行，需 admin 启动）。"
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

      <h3>DatasetSnapshot（split guard 通过才可注册）</h3>
      {snaps === null ? (
        <p className="muted">加载中…</p>
      ) : snaps.length === 0 ? (
        <p className="muted">暂无快照。经 API 注册（train/val 门店/session/sha 零交集守卫）。</p>
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
            {snaps.map((s) => (
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
                  <span className={`pill pill-${s.status === "registered" ? "healthy" : "unavailable"}`}>
                    {String(s.status)}
                  </span>
                </td>
                <td>
                  <button
                    disabled={busy || s.status !== "registered"}
                    onClick={() => onDryRun(String(s.snapshot_id))}
                  >
                    dry-run
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>TrainingRun（dry-run → 授权 → candidate → 独立发布审批）</h3>
      {runs === null ? (
        <p className="muted">加载中…</p>
      ) : runs.length === 0 ? (
        <p className="muted">暂无运行。dry-run 将展示批准后将执行的命令、MPS G0、算力预算与停止线。</p>
      ) : (
        runs.map((r) => (
          <div key={r.run_id} style={{ marginBottom: 12 }}>
            <p>
              <span className="muted">{r.run_id.slice(0, 8)}…</span>{" "}
              <span className={`pill pill-${r.kind === "authorized" ? "healthy" : "degraded"}`}>{r.kind}</span>{" "}
              <span className="pill pill-degraded">publish: {r.publish_status}</span>{" "}
              {r.approved_by && <span className="muted">批准人：{r.approved_by}</span>}
            </p>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
              {JSON.stringify(JSON.parse(r.command_json), null, 1)}
            </pre>
            <p className="muted" style={{ fontSize: 12 }}>
              停止线：{JSON.stringify(JSON.parse(r.stop_lines_json))}
            </p>
          </div>
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
      {legacyRuns.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>run</th>
              <th>epochs</th>
            </tr>
          </thead>
          <tbody>
            {legacyRuns.map((r) => (
              <tr key={String(r.run)}>
                <td>{String(r.run)}</td>
                <td>{Array.isArray(r.epochs) ? r.epochs.length : 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        红线：训练启动需显式授权；训练完成只产生 candidate，不自动发布；发布为独立 admin
        审批；旧 /retrain auto_switch=true 不进新平台。
      </p>
    </section>
  );
}
