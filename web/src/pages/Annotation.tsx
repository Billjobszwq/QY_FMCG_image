import { useCallback, useEffect, useRef, useState } from "react";
import {
  HealthBody,
  LabelingBatch,
  ReconcileReport,
  createLabelingBatch,
  fetchLabelingBatches,
  fetchLabelingInbox,
  fetchReconcile,
  importLabelingFiles,
} from "../api";

export default function Annotation({ health }: { health: HealthBody | null }) {
  const ls = health?.services.find((s) => s.name === "label_studio");
  const up = ls?.status === "healthy";

  const [batches, setBatches] = useState<LabelingBatch[] | null>(null);
  const [inbox, setInbox] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [reconcile, setReconcile] = useState<ReconcileReport | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [targetBatch, setTargetBatch] = useState<string>("");

  const reload = useCallback(async () => {
    try {
      const [b, i] = await Promise.all([fetchLabelingBatches(), fetchLabelingInbox()]);
      setBatches(b.batches);
      setInbox(i.count);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const onCreate = async () => {
    if (!name.trim()) return;
    setBusy("创建中…");
    try {
      const out = await createLabelingBatch(name.trim());
      setName("");
      setTargetBatch(out.batch.batch_id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onImport = async () => {
    const files = Array.from(fileRef.current?.files ?? []);
    if (!targetBatch || files.length === 0) return;
    setBusy(`导入 ${files.length} 张（真实识别预标注，可能需要数十秒）…`);
    try {
      const report = await importLabelingFiles(targetBatch, files);
      if (fileRef.current) fileRef.current.value = "";
      await reload();
      setReconcile(await fetchReconcile(targetBatch));
      setError(
        `导入完成：assisted ${JSON.stringify(report["assisted"])} / blind ${JSON.stringify(
          report["blind"]
        )} / predictions_written=${report["predictions_written"]}`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onReconcile = async (batchId: string) => {
    setBusy("对账中…");
    try {
      setReconcile(await fetchReconcile(batchId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section>
      <h2>标注审核（M4）</h2>
      {!health && <p className="muted">正在加载…</p>}
      {health && !up && (
        <div className="banner banner-degraded">
          Label Studio（8300）当前不可用（{ls?.detail ?? "unavailable"}）。请先运行
          scripts/start_label_studio.sh。
        </div>
      )}
      {up && (
        <p>
          Label Studio 可用：<a href="http://127.0.0.1:8300" target="_blank" rel="noreferrer">打开 8300</a>
          {inbox !== null && (
            <>
              {" "}· webhook inbox：<span className="pill pill-healthy">{inbox} 条事件</span>
            </>
          )}
        </p>
      )}

      {busy && <p className="pill pill-degraded">{busy}</p>}
      {error && <p className="muted">{error}</p>}

      <h3>标注批次（assisted / blind 双项目）</h3>
      {batches === null ? (
        <p className="muted">加载中…</p>
      ) : batches.length === 0 ? (
        <p className="muted">暂无批次。创建试验批次并导入照片开始 E2E。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>批次</th>
              <th>batch_id</th>
              <th>assisted</th>
              <th>blind</th>
              <th>任务数</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.batch_id}>
                <td>{b.name}</td>
                <td className="muted">{b.batch_id.slice(0, 8)}…</td>
                <td>
                  {b.assisted_project_id !== null && (
                    <a href={`http://127.0.0.1:8300/projects/${b.assisted_project_id}`} target="_blank" rel="noreferrer">
                      #{b.assisted_project_id}
                    </a>
                  )}
                </td>
                <td>
                  {b.blind_project_id !== null && (
                    <a href={`http://127.0.0.1:8300/projects/${b.blind_project_id}`} target="_blank" rel="noreferrer">
                      #{b.blind_project_id}
                    </a>
                  )}
                </td>
                <td>{b.task_count}</td>
                <td>
                  <span className={`pill pill-${b.status === "reconciled" || b.status === "closed" ? "healthy" : "degraded"}`}>
                    {b.status}
                  </span>
                </td>
                <td>
                  <button onClick={() => onReconcile(b.batch_id)} disabled={busy !== null}>
                    对账
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {reconcile && (
        <div>
          <h3>
            对账报告 {reconcile.batch_id.slice(0, 8)}…{" "}
            <span className={`pill pill-${reconcile.consistent ? "healthy" : "unavailable"}`}>
              {reconcile.consistent ? "consistent" : "inconsistent（显式标记，不谎报）"}
            </span>{" "}
            <span className={`pill pill-${reconcile.blind_no_predictions ? "healthy" : "unavailable"}`}>
              blind_no_predictions={String(reconcile.blind_no_predictions)}
            </span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>项目</th>
                <th>tasks</th>
                <th>annotations(API)</th>
                <th>predictions(API)</th>
                <th>inbox 事件</th>
                <th>inbox 标注事件</th>
                <th>一致</th>
              </tr>
            </thead>
            <tbody>
              {(["assisted", "blind"] as const).map((k) => {
                const p = reconcile.projects[k];
                return (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{p.tasks}</td>
                    <td>{p.annotations_api}</td>
                    <td>{p.predictions_api}</td>
                    <td>{p.inbox_events}</td>
                    <td>{p.inbox_annotation_events}</td>
                    <td>
                      <span className={`pill pill-${p.consistent ? "healthy" : "unavailable"}`}>
                        {String(p.consistent)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h3>新建批次 / 导入照片</h3>
      <div className="row-actions" style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <input
          placeholder="批次名（如 trial10）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button onClick={onCreate} disabled={busy !== null || !name.trim()}>
          创建双项目批次
        </button>
      </div>
      <div className="row-actions" style={{ display: "flex", gap: 8 }}>
        <select value={targetBatch} onChange={(e) => setTargetBatch(e.target.value)}>
          <option value="">选择目标批次…</option>
          {(batches ?? []).map((b) => (
            <option key={b.batch_id} value={b.batch_id}>
              {b.name}（{b.batch_id.slice(0, 8)}…）
            </option>
          ))}
        </select>
        <input type="file" multiple accept="image/*" ref={fileRef} />
        <button onClick={onImport} disabled={busy !== null || !targetBatch}>
          导入并写预标注
        </button>
        <button onClick={reload} disabled={busy !== null}>
          刷新
        </button>
      </div>

      <p className="muted">
        红线：blind 项目绝不写入 prediction（对账 blind_no_predictions 校验）；webhook inbox
        按 (source, event_id) 去重，API 对账以 LS 为事实源，不一致时显式标记。
        人工标注/双审/仲裁需授权后进行；平台不自动启动任何训练。
      </p>
    </section>
  );
}
