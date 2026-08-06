import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  LoopRunRow,
  LoopRunView,
  RunRow,
  RunView,
  approveRun,
  csrfToken,
  fetchLoopRun,
  fetchLoopRuns,
  fetchRun,
  fetchRuns,
  gateLoop,
  startLoop,
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
      <p className="muted">
        FMCG 多模型级联（S0–S5）任务请看
        <Link to="/cascade">级联任务</Link>；模型 hot/warm/cold 驻留请看
        <Link to="/models-runtime">模型驻留</Link>。本页为底层 GraphRun 视图。
      </p>
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

      <LoopV2Section />
    </section>
  );
}

// ---------- U5-3：Graph+Loop v2（轮次/决策原因/等待项/成本/停止原因） ----------

const LOOP_STATUS_CN: Record<string, string> = {
  completed: "完成",
  failed: "失败",
  waiting_human: "等待人工",
  running: "运行中",
  pending: "待启动",
  cancelled: "已取消",
};

const DECISION_CN: Record<string, string> = {
  next: "顺行",
  on_fail: "失败分支",
  feedback: "误差回流",
  human_gate: "人工门",
  terminal: "终点",
  no_edge: "无匹配路由",
};

const STOP_CN: Record<string, string> = {
  budget_rounds: "轮次预算超限",
  no_edge: "路由未定义",
  no_router: "缺少路由器",
};

function LoopV2Section() {
  const [runs, setRuns] = useState<LoopRunRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<LoopRunView | null>(null);
  const [busy, setBusy] = useState(false);
  const [sourceId, setSourceId] = useState("photo1106");
  const [batchSize, setBatchSize] = useState(8);
  const [maxRounds, setMaxRounds] = useState(3);
  const logged = csrfToken() !== null;

  const refresh = useCallback(async () => {
    try {
      const b = await fetchLoopRuns();
      setRuns(b.runs);
      setError(null);
    } catch (e) {
      setRuns(null);
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const view = await startLoop({
        source_id: sourceId,
        batch_size: batchSize,
        max_rounds: maxRounds,
      });
      setDetail(view);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const open = async (runId: string) => {
    try {
      setDetail(await fetchLoopRun(runId));
    } catch (e) {
      setError(String(e));
    }
  };

  const gate = async (runId: string, approved: boolean) => {
    setBusy(true);
    try {
      setDetail(await gateLoop(runId, approved));
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3>Loop v2：照片→质量→人工→数据集→识别→误差回流</h3>
      <div className="row-actions" style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="photo1106">照片1106（真实货架照 213 张）</option>
          <option value="bad_samples">bad_samples（质量负样本 5 张）</option>
        </select>
        <label>
          每轮批量{" "}
          <input
            type="number" min={1} max={64} value={batchSize}
            style={{ width: 60 }}
            onChange={(e) => setBatchSize(Number(e.target.value))}
          />
        </label>
        <label>
          最大轮次{" "}
          <input
            type="number" min={1} max={10} value={maxRounds}
            style={{ width: 60 }}
            onChange={(e) => setMaxRounds(Number(e.target.value))}
          />
        </label>
        <button onClick={start} disabled={busy || !logged}>
          启动 Loop（仅 admin）
        </button>
      </div>
      {!logged && (
        <p className="muted">
          未登录：请先在右上角登录（启动/人工门审批仅限 admin）。
        </p>
      )}
      {error && <p className="pill pill-unavailable">错误：{error}</p>}

      {runs === null ? (
        <p className="muted">Loop v2 运行列表不可用（未登录或 API 未启用）。</p>
      ) : runs.length === 0 ? (
        <p className="muted">暂无 Loop v2 运行。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>run_id</th>
              <th>状态</th>
              <th>轮次</th>
              <th>停止原因</th>
              <th>等待项 / 下一节点</th>
              <th>成本（节点执行）</th>
              <th>创建时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id}>
                <td className="muted">{r.run_id.slice(0, 8)}…</td>
                <td>
                  <span className={`pill pill-${r.status === "completed" ? "healthy" : r.status === "failed" ? "unavailable" : "degraded"}`}>
                    {LOOP_STATUS_CN[r.status] ?? r.status}
                  </span>
                </td>
                <td>{r.rounds_used ?? 0}</td>
                <td className="muted">
                  {r.stop_reason ? (STOP_CN[r.stop_reason] ?? r.stop_reason) : "—"}
                </td>
                <td className="muted">
                  {r.waiting_for ?? "—"}{r.next_node ? ` → ${r.next_node}` : ""}
                </td>
                <td>{r.cost_nodes ?? 0}</td>
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
          <h4>
            Loop 详情：{detail.run_id.slice(0, 8)}…（
            {LOOP_STATUS_CN[detail.status] ?? detail.status}，轮次 {detail.rounds_used ?? 0}
            {detail.stop_reason
              ? `，停止原因：${STOP_CN[detail.stop_reason] ?? detail.stop_reason}`
              : ""}
            ）
          </h4>
          {detail.error && <p className="muted">错误：{detail.error}</p>}
          {detail.waiting_for && (
            <p>
              等待人工：{detail.waiting_for}{" "}
              <button onClick={() => gate(detail.run_id, true)} disabled={busy || !logged}>
                批准并继续
              </button>{" "}
              <button onClick={() => gate(detail.run_id, false)} disabled={busy || !logged}>
                拒绝（终态）
              </button>
            </p>
          )}
          {detail.cost_detail && (
            <p className="muted">
              成本：节点执行 {detail.cost_detail.node_executions} 次，
              质量评估 {detail.cost_detail.quality_evals} 轮。
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>轮次</th>
                <th>节点</th>
                <th>决策</th>
                <th>决策原因</th>
                <th>下一节点</th>
              </tr>
            </thead>
            <tbody>
              {detail.trail.map((t, i) => (
                <tr key={i}>
                  <td>{t.round}</td>
                  <td>{t.node}</td>
                  <td>
                    <span className={`pill pill-${t.decision === "feedback" ? "degraded" : t.decision === "human_gate" ? "degraded" : t.decision === "no_edge" ? "unavailable" : "healthy"}`}>
                      {DECISION_CN[t.decision] ?? t.decision}
                    </span>
                  </td>
                  <td className="muted">{t.reason}</td>
                  <td>{t.next ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
