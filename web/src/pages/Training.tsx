import { useEffect, useState } from "react";
import { fetchMonitorLive, fetchMonitorOverview } from "../api";

export default function Training() {
  const [live, setLive] = useState<Record<string, unknown> | null>(null);
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchMonitorLive(), fetchMonitorOverview()])
      .then(([l, o]) => {
        setLive(l);
        setOverview(o);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const runs = (overview?.yolo_runs as Array<Record<string, unknown>> | undefined) ?? [];

  return (
    <section>
      <h2>训练模型（只读）</h2>
      <div className="banner banner-degraded">
        当前无训练授权：training_started=false。本页仅展示 8092 监控的只读视图。
      </div>
      {error && <div className="banner banner-unavailable">监控不可用：{error}</div>}
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
      {runs.length > 0 && (
        <>
          <h3>YOLO 运行（8092 只读）</h3>
          <table>
            <thead>
              <tr>
                <th>run</th>
                <th>epochs</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={String(r.run)}>
                  <td>{String(r.run)}</td>
                  <td>{Array.isArray(r.epochs) ? r.epochs.length : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
