import { useCallback, useEffect, useRef, useState } from "react";
import {
  RunRow,
  RunView,
  approveRun,
  fetchRun,
  fetchRuns,
  startRun,
  uploadAsset,
} from "../api";

const FMCG = "fmcg_photo_inspection_v1";
const SYSHEALTH = "system_health_v1";

export default function GraphRuns() {
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunView | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const b = await fetchRuns();
      setRuns(b.runs);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!detail) return;
    if (detail.run.status === "waiting_human" || detail.run.status === "running") {
      const t = setInterval(async () => {
        try {
          setDetail(await fetchRun(detail.run.run_id));
        } catch {
          /* ignore */
        }
      }, 2000);
      return () => clearInterval(t);
    }
  }, [detail]);

  const open = async (runId: string) => {
    try {
      setDetail(await fetchRun(runId));
    } catch (e) {
      setError(String(e));
    }
  };

  const inspect = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const asset = await uploadAsset(file);
      const view = await startRun({
        graph_name: FMCG,
        input: { photo_sha256: asset.sha256 },
        idempotency_key: `web-${asset.sha256}`,
      });
      setDetail(view);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const runHealth = async () => {
    setBusy(true);
    setError(null);
    try {
      const view = await startRun({ graph_name: SYSHEALTH, input: {} });
      setDetail(view);
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const decide = async (approved: boolean) => {
    if (!detail) return;
    setBusy(true);
    try {
      setDetail(await approveRun(detail.run.run_id, approved));
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>Graph Runs</h2>
      <div className="row-actions" style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) inspect(f);
          }}
        />
        <button onClick={runHealth} disabled={busy}>
          运行 system_health_v1
        </button>
      </div>
      {error && <p className="pill pill-unavailable">错误：{error}</p>}

      <h3>Run 列表</h3>
      {runs === null ? (
        <p className="muted">Graph Runtime 加载中…（若 8400 以 M1 模式运行则无此 API）</p>
      ) : runs.length === 0 ? (
        <p className="muted">暂无 Run。上传一张照片开始第一条真实流程。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>run_id</th>
              <th>graph</th>
              <th>状态</th>
              <th>创建时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id}>
                <td className="muted">{r.run_id.slice(0, 8)}…</td>
                <td>{r.graph_name}</td>
                <td>
                  <span className={`pill pill-${r.status === "completed" ? "healthy" : r.status === "waiting_human" ? "degraded" : r.status === "failed" ? "unavailable" : "degraded"}`}>
                    {r.status}
                  </span>
                </td>
                <td className="muted">{r.created_at}</td>
                <td>
                  <button onClick={() => open(r.run_id)}>详情</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {detail && (
        <>
          <h3>Run 详情：{detail.run.run_id.slice(0, 8)}…（{detail.run.graph_name}@{detail.run.graph_version}）</h3>
          <p>
            状态：<span className={`pill pill-${detail.run.status === "completed" ? "healthy" : detail.run.status === "failed" ? "unavailable" : "degraded"}`}>{detail.run.status}</span>
            {detail.run.error && <span className="muted"> 错误：{detail.run.error}</span>}
          </p>
          {detail.run.status === "waiting_human" && (
            <p>
              <button onClick={() => decide(true)} disabled={busy}>批准人工门</button>{" "}
              <button onClick={() => decide(false)} disabled={busy}>拒绝</button>
            </p>
          )}
          <h4>节点时间线</h4>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>节点</th>
                <th>attempt</th>
                <th>状态</th>
                <th>开始</th>
                <th>结束</th>
                <th>error</th>
              </tr>
            </thead>
            <tbody>
              {detail.nodes.map((n, i) => (
                <tr key={i}>
                  <td>{n.seq}</td>
                  <td>{n.node_name}</td>
                  <td>{n.attempt}</td>
                  <td>
                    <span className={`pill pill-${n.status === "completed" ? "healthy" : n.status === "failed" ? "unavailable" : "degraded"}`}>{n.status}</span>
                  </td>
                  <td className="muted">{n.started_at}</td>
                  <td className="muted">{n.ended_at ?? "—"}</td>
                  <td className="muted">{n.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4>Evidence</h4>
          {detail.evidence.length === 0 ? (
            <p className="muted">暂无 EvidenceBundle。</p>
          ) : (
            detail.evidence.map((ev) => (
              <details key={ev.evidence_id}>
                <summary>{ev.evidence_id.slice(0, 8)}…（{ev.kind}）</summary>
                <pre>{ev.manifest_json}</pre>
              </details>
            ))
          )}
          {detail.run.output_json && (
            <>
              <h4>输出</h4>
              <pre>{JSON.stringify(detail.run.output_json, null, 2)}</pre>
            </>
          )}
        </>
      )}
    </section>
  );
}
