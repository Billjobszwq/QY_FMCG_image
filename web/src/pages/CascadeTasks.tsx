import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  CascadeTaskDetail,
  CascadeTaskRow,
  CascadeTrailItem,
  cancelCascadeTask,
  csrfToken,
  fetchCascadeRegions,
  fetchCascadeTask,
  fetchCascadeTasks,
  fetchCascadeTrail,
} from "../api";

// VLM-016：页面一律业务语言；技术字段（模型哈希/策略版本/risk/token）折叠。

const TIER_CN: Record<string, string> = {
  fast: "fast（快速）",
  standard: "standard（标准）",
  deep: "deep（深度）",
  expert: "expert（专家）",
};

const STAGE_OF_NODE: Record<string, string> = {
  quality: "S0 照片检查",
  scene: "S0 照片检查",
  detect: "S1 检测+快分类",
  classify_fast: "S1 检测+快分类",
  risk_s1: "S1 检测+快分类",
  segment: "S2 SAM 精修",
  reclassify: "S2 SAM 精修",
  risk_s2: "S2 SAM 精修",
  retrieve: "S3 召回",
  risk_s3: "S3 召回",
  vlm_rerank: "S4 VLM 裁决",
  risk_s4: "S4 VLM 裁决",
  human_review: "S5 人工审核",
  finalize: "已完成",
};

const DECISION_CN: Record<string, string> = {
  next: "顺行",
  escalate: "升级下一阶段",
  accept: "自动接受",
  human: "转人工",
  abstain: "拒识（unknown）",
  on_fail: "失败分支",
  terminal: "终点",
};

function resultMeta(task: CascadeTaskRow): Record<string, unknown> {
  try {
    return JSON.parse(task.result_json ?? "{}") ?? {};
  } catch {
    return {};
  }
}

function currentStage(trail: CascadeTrailItem[]): string {
  for (let i = trail.length - 1; i >= 0; i--) {
    const s = STAGE_OF_NODE[trail[i].node];
    if (s) return s;
  }
  return "尚未开始";
}

function upgradeReason(trail: CascadeTrailItem[]): string {
  const esc = [...trail].reverse().find(
    (t) => t.decision === "escalate" || t.decision === "human",
  );
  return esc ? esc.reason : "无升级：在当前阶段直接得出结论";
}

function pendingHuman(task: CascadeTaskRow, trail: CascadeTrailItem[]): string {
  if (task.status === "waiting_human") return "待人工";
  if (trail.some((t) => t.decision === "human")) return "待人工";
  return "自动";
}

export default function CascadeTasks() {
  const [tasks, setTasks] = useState<CascadeTaskRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [detail, setDetail] = useState<CascadeTaskDetail | null>(null);
  const [trail, setTrail] = useState<CascadeTrailItem[]>([]);
  const [regions, setRegions] = useState<Array<Record<string, unknown>>>([]);
  const [busy, setBusy] = useState(false);
  const logged = csrfToken() !== null;

  const reload = useCallback(async () => {
    try {
      const d = await fetchCascadeTasks();
      setTasks(d.tasks);
      setDisabled(false);
      setError(null);
    } catch (e) {
      setTasks(null);
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("401")) setError("未登录");
      else if (msg.includes("404")) setDisabled(true);
      else setError(msg);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const open = async (taskId: string) => {
    setBusy(true);
    setError(null);
    try {
      const [d, t, r] = await Promise.all([
        fetchCascadeTask(taskId),
        fetchCascadeTrail(taskId).catch(() => ({ trail: [] })),
        fetchCascadeRegions(taskId).catch(() => ({ regions: [] })),
      ]);
      setDetail(d);
      setTrail(t.trail);
      setRegions(r.regions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (taskId: string) => {
    setBusy(true);
    try {
      await cancelCascadeTask(taskId);
      await reload();
      setDetail(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const billingTotal = (detail?.billing ?? []).reduce(
    (s, b) => s + (Number(b.billed_cost) || 0), 0,
  );

  return (
    <section>
      <h2>级联任务（shadow 默认，production_switch=false）</h2>
      <p className="muted">
        单文件 / 批量 / URL / API / Agent 五入口共用同一 RecognitionTask 与
        Graph+Loop v2。旧 8091 识别链路不受影响。相关页面：
        <Link to="/models-runtime">模型驻留</Link> ·{" "}
        <Link to="/packaging">新包装裁决</Link>
      </p>
      {disabled && (
        <div className="banner banner-degraded">
          级联 API 未启用：当前 8400 进程尚未注入 cascade
          service（shadow 阶段诚实状态）。旧识别入口仍可用。
        </div>
      )}
      {!logged && !disabled && (
        <div className="banner banner-degraded">
          需要登录：请在右上角登录后查看级联任务。
        </div>
      )}
      {error && <div className="banner banner-unavailable">错误：{error}</div>}
      {busy && <p className="muted">处理中…</p>}

      <h3>任务列表</h3>
      {disabled ? (
        <p className="muted">暂无级联任务（cascade API 未启用，见上方说明）。</p>
      ) : tasks === null && !error ? (
        <p className="muted">加载中…</p>
      ) : tasks === null ? (
        <p className="muted">任务列表不可用（{error ?? "未知原因"}）。</p>
      ) : tasks.length === 0 ? (
        <p className="muted">暂无级联任务（空队列是诚实状态，不是错误）。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>入口</th>
              <th>客户档位</th>
              <th>状态</th>
              <th>发起人</th>
              <th>时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => {
              const meta = resultMeta(t);
              return (
                <tr key={t.task_id}>
                  <td>{t.entry}</td>
                  <td>{TIER_CN[String(meta.tier ?? "")] ?? "—"}</td>
                  <td>
                    <span
                      className={`pill pill-${
                        t.status === "completed"
                          ? "healthy"
                          : t.status === "failed"
                            ? "unavailable"
                            : "degraded"
                      }`}
                    >
                      {t.status === "waiting_human" ? "待人工" : t.status}
                    </span>
                  </td>
                  <td>{t.created_by}</td>
                  <td className="muted">{t.created_at}</td>
                  <td>
                    <button onClick={() => open(t.task_id)}>详情</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {detail && (
        <>
          <h3>任务详情：{detail.task.task_id.slice(0, 8)}…</h3>
          <div className="cards">
            <div className="card">
              <div className="k">客户档位</div>
              <div className="v sm">
                {TIER_CN[String(resultMeta(detail.task).tier ?? "")] ?? "—"}
              </div>
            </div>
            <div className="card">
              <div className="k">当前阶段</div>
              <div className="v sm">{currentStage(trail)}</div>
            </div>
            <div className="card">
              <div className="k">自动 / 待人工</div>
              <div className="v sm">{pendingHuman(detail.task, trail)}</div>
            </div>
            <div className="card">
              <div className="k">剩余 SLA（队列业务 SLA）</div>
              <div className="v sm">
                {detail.remaining_sla
                  ? detail.remaining_sla.expired
                    ? "已到期（转人工）"
                    : `${detail.remaining_sla.remaining_hours}h / ${detail.remaining_sla.sla_hours}h`
                  : "—"}
              </div>
            </div>
            <div className="card">
              <div className="k">成本（rate-card.v1）</div>
              <div className="v sm">{billingTotal.toFixed(2)} 单位</div>
            </div>
          </div>
          <p className="muted">为何升级：{upgradeReason(trail)}</p>

          <h4>阶段轨迹（为何走到这一步）</h4>
          {trail.length === 0 ? (
            <p className="muted">暂无轨迹。</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>阶段</th>
                  <th>决策</th>
                  <th>为何</th>
                </tr>
              </thead>
              <tbody>
                {trail.map((t, i) => (
                  <tr key={i}>
                    <td>{STAGE_OF_NODE[t.node] ?? t.node}</td>
                    <td>
                      <span
                        className={`pill pill-${
                          t.decision === "human" || t.decision === "escalate"
                            ? "degraded"
                            : t.decision === "abstain"
                              ? "unavailable"
                              : "healthy"
                        }`}
                      >
                        {DECISION_CN[t.decision] ?? t.decision}
                      </span>
                    </td>
                    <td className="muted">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4>检测区域（{regions.length}）</h4>
          {regions.length === 0 ? (
            <p className="muted">无区域（可能尚未到检测阶段）。</p>
          ) : (
            <pre className="tech-pre">{JSON.stringify(regions, null, 2)}</pre>
          )}

          {detail.task.status !== "completed" &&
            detail.task.status !== "failed" && (
              <p>
                <button onClick={() => cancel(detail.task.task_id)} disabled={busy}>
                  取消任务
                </button>
              </p>
            )}

          <details className="tech-details">
            <summary>技术字段（模型哈希 / 策略版本 / risk / token）</summary>
            {trail.map((t, i) => (
              <div key={i}>
                <p className="muted">
                  {t.node}：policy={String(t.detail?.policy_version ?? "—")}，
                  risk={String(t.detail?.risk ?? "—")}，
                  tokens={String(t.detail?.tokens ?? "—")}，
                  模型哈希={String(t.detail?.model_hash ?? t.detail?.model ?? "—")}
                </p>
              </div>
            ))}
            {detail.result && (
              <pre className="tech-pre">
                {JSON.stringify(detail.result, null, 2)}
              </pre>
            )}
            <h5>成本明细与证据</h5>
            {(detail.billing ?? []).length === 0 ? (
              <p className="muted">暂无成本账本。</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>能力</th>
                    <th>成本</th>
                    <th>证据</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail.billing ?? []).map((b, i) => (
                    <tr key={i}>
                      <td>{String(b.capability ?? "—")}</td>
                      <td>{String(b.billed_cost ?? "—")}</td>
                      <td className="muted">{String(b.evidence_id ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </details>
        </>
      )}
    </section>
  );
}
