import { useCallback, useEffect, useState } from "react";
import {
  AssetRow, AssetsSummary, buildGoldQueue, claimReviewTask, csrfToken,
  exportReview, fetchAssetsList, fetchAssetsSummary, fetchGoldConfusion,
  fetchGoldStatus, fetchReviewStatus, fetchReviewTasks, GoldStatusBody,
  ReviewTaskRow, submitGoldVerdict, submitReview,
} from "../api";

const PURPOSE_CN: Record<string, string> = {
  detector_training: "Detector 训练候选",
  classifier_retrieval: "分类/检索",
  packaging_unknown_sku: "包装版本/未知 SKU",
  quality_negative: "质量负样本",
  eval_frozen: "评估冻结集",
  to_label: "待标注",
  rejection_evidence: "拒绝证据",
};

const PAGE = 50;

const STRATUM_CN: Record<string, string> = {
  fail: "自动判 fail 层",
  pass: "自动判 pass 层",
  waiting_human: "无自动结论层",
};

function GoldSection() {
  const [gold, setGold] = useState<GoldStatusBody | null>(null);
  const [confusion, setConfusion] = useState<Record<string, number> | null>(null);
  const [msg, setMsg] = useState("");

  const reload = useCallback(async () => {
    const [st, cm] = await Promise.all([fetchGoldStatus(), fetchGoldConfusion()]);
    setGold(st);
    setConfusion(cm);
  }, []);

  useEffect(() => {
    reload().catch((e) => setMsg(String(e)));
  }, [reload]);

  const onBuild = async () => {
    try {
      const r = await buildGoldQueue(500);
      setMsg(`建队完成：新增 ${r.added}，队列共 ${r.total_queue}`);
      await reload();
    } catch (e) {
      setMsg(`建队失败：${e}`);
    }
  };

  const onVerdict = async (sha256: string, v: "pass" | "fail") => {
    try {
      await submitGoldVerdict(sha256, v);
      await reload();
    } catch (e) {
      setMsg(`提交失败：${e}`);
    }
  };

  if (!gold) return <p className="muted">金标准加载中…</p>;
  return (
    <>
      <span className="kicker">数据与资产 · data_steward</span>
      <h3>人工质量金标准（分层抽样，不可变）</h3>
      <div className="cards">
        <div className="card"><div className="num">{gold.waiting_human}</div><div className="muted">等待人工（waiting_human）</div></div>
        <div className="card"><div className="num">{gold.done}</div><div className="muted">人工已完成</div></div>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button onClick={() => void onBuild()}>分层建队（500）</button>
        <span className="muted">需登录；人工结论以服务端 session 身份落库，追加式不可变</span>
      </div>
      {msg && <p className="muted">{msg}</p>}
      <table className="table">
        <thead><tr><th>SHA</th><th>引用</th><th>层</th><th>状态</th><th>人工结论</th><th>操作</th></tr></thead>
        <tbody>
          {gold.items.slice(0, 100).map((it) => (
            <tr key={it.sha256}>
              <td className="muted">{it.sha256.slice(0, 12)}…</td>
              <td className="muted" style={{ maxWidth: 280, overflowWrap: "anywhere" }}>{it.source_uri}</td>
              <td>{STRATUM_CN[it.stratum] ?? it.stratum}</td>
              <td>{it.status === "waiting_human" ? "等待人工" : "已完成"}</td>
              <td>{it.human_verdict ?? "—"}</td>
              <td>
                {it.status === "waiting_human" && csrfToken() ? (
                  <span className="row" style={{ gap: 4 }}>
                    <button onClick={() => void onVerdict(it.sha256, "pass")}>通过</button>
                    <button onClick={() => void onVerdict(it.sha256, "fail")}>不通过</button>
                  </span>
                ) : (
                  <span className="muted">{it.status === "waiting_human" ? "登录后审核" : "不可改"}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {gold.items.length === 0 && (
        <p className="muted">队列为空；点击「分层建队」从本地真实照片抽样（manifest-only 不入队）。</p>
      )}
      {confusion && confusion.pairs > 0 && (
        <details>
          <summary>混淆矩阵（仅对有人工结论的 {confusion.pairs} 对）</summary>
          <table className="table">
            <thead><tr><th>自动 \ 人工</th><th>fail</th><th>pass</th></tr></thead>
            <tbody>
              <tr><td>fail</td><td>{confusion.auto_fail_human_fail}</td><td>{confusion.auto_fail_human_pass}</td></tr>
              <tr><td>pass</td><td>{confusion.auto_pass_human_fail}</td><td>{confusion.auto_pass_human_pass}</td></tr>
              <tr><td>无结论</td><td>{confusion.auto_none_human_fail}</td><td>{confusion.auto_none_human_pass}</td></tr>
            </tbody>
          </table>
        </details>
      )}
    </>
  );
}

const REVIEW_STATUS_CN: Record<string, string> = {
  pending: "待认领",
  claimed: "已认领待审",
  awaiting_second: "等待第二审",
  awaiting_arbitration: "分歧待仲裁",
  finalized: "已终态",
};

function ReviewSection() {
  const [status, setStatus] = useState<{
    n_tasks: number;
    status_distribution: Record<string, number>;
    batch_plan?: {
      stage?: string;
      status: string;
      n_total?: number;
      n_finalized?: number;
      next_size?: number | null;
      note?: string;
    };
  } | null>(null);
  const [tasks, setTasks] = useState<ReviewTaskRow[] | null>(null);
  const [msg, setMsg] = useState("");
  const [boxInputs, setBoxInputs] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    setStatus(await fetchReviewStatus());
    if (csrfToken()) {
      try {
        setTasks((await fetchReviewTasks()).tasks);
      } catch {
        setTasks(null);
      }
    }
  }, []);

  useEffect(() => {
    reload().catch((e) => setMsg(String(e)));
  }, [reload]);

  const onClaim = async (t: ReviewTaskRow) => {
    try {
      const r = await claimReviewTask(t.claim_token);
      setMsg(r.claimed ? `已认领 ${t.task_id}` : "该任务已被认领");
      await reload();
    } catch (e) {
      setMsg(`认领失败：${e}`);
    }
  };

  const onSubmit = async (t: ReviewTaskRow, verdict: string,
                          role = "annotator") => {
    const raw = boxInputs[t.task_id] ?? "";
    const box = raw.split(/[,，\s]+/).map(Number);
    if (box.length !== 4 || box.some((v) => !Number.isFinite(v))) {
      setMsg("请先填写合法框：x1,y1,x2,y2");
      return;
    }
    try {
      const r = await submitReview(t.task_id, verdict, box, role);
      setMsg(r.finalized ? `${t.task_id} 已终态` : `${t.task_id}：${r.status}`);
      await reload();
    } catch (e) {
      setMsg(`提交失败：${e}`);
    }
  };

  const onExport = async () => {
    try {
      const r = await exportReview();
      setMsg(`导出完成：${r.n_finalized}/${r.n_tasks} 终态，SHA ${r.sha256.slice(0, 12)}…`);
    } catch (e) {
      setMsg(`导出失败：${e}`);
    }
  };

  if (!status) return <p className="muted">审核队列加载中…</p>;
  const d = status.status_distribution;
  const bp = status.batch_plan;
  const BP_CN: Record<string, string> = {
    waiting_human: "等待人工（禁止伪造通过）",
    gate_failed: "批次质量不达标，已停止扩展",
    ready: "可扩展现有阶梯",
    done: "全部阶梯完成",
    empty: "队列为空",
  };
  return (
    <>
      <h3>标注审核闭环（链接派发/认领/单审/双审/仲裁）</h3>
      <div className="cards">
        <div className="card"><div className="num">{status.n_tasks}</div><div className="muted">队列总数</div></div>
        <div className="card"><div className="num">{d.pending ?? 0}</div><div className="muted">待认领</div></div>
        <div className="card"><div className="num">{(d.claimed ?? 0) + (d.awaiting_second ?? 0)}</div><div className="muted">审核中</div></div>
        <div className="card"><div className="num">{d.awaiting_arbitration ?? 0}</div><div className="muted">待仲裁</div></div>
        <div className="card"><div className="num">{d.finalized ?? 0}</div><div className="muted">已终态（final_box 只来自人工）</div></div>
      </div>
      <p className="muted">
        SAM 预测永远不是最终标注；未完成任务不得伪造完成；
        队列与事件追加式不可变。
      </p>
      {bp && (
        <p className="muted">
          分批扩展（100→500→2000→全 eligible）：
          当前批次 {bp.stage ?? "—"}，状态 {BP_CN[bp.status] ?? bp.status}
          {typeof bp.n_total === "number" &&
            `，进度 ${bp.n_finalized ?? 0}/${bp.n_total}`}
          {bp.next_size != null && `，下一批 ${bp.next_size === -1 ? "全 eligible" : bp.next_size}`}
          。任何批次质量不达标立即停止。
        </p>
      )}
      {msg && <p className="muted">{msg}</p>}
      {!csrfToken() && (
        <p className="muted">任务明细需登录；登录后显示认领链接与提交入口。</p>
      )}
      {csrfToken() && (
        <div className="row" style={{ gap: 8 }}>
          <button onClick={() => void onExport()}>不可变导出（admin）</button>
        </div>
      )}
      {tasks && tasks.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>photo</th><th>模式</th><th>状态</th><th>认领人</th>
              <th>final box</th><th>审核框 (x1,y1,x2,y2)</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.slice(0, 100).map((t) => (
              <tr key={t.task_id}>
                <td>{t.photo_id}</td>
                <td>{t.review_mode === "blind_review" ? "单审（盲抽）" : "双审"}</td>
                <td>{REVIEW_STATUS_CN[t.status] ?? t.status}</td>
                <td>{t.claimed_by ?? "—"}</td>
                <td className="muted">{t.final_box ? t.final_box.join(",") : "—"}</td>
                <td>
                  <input
                    style={{ width: 140 }}
                    placeholder="x1,y1,x2,y2"
                    value={boxInputs[t.task_id] ?? ""}
                    onChange={(e) => setBoxInputs({
                      ...boxInputs, [t.task_id]: e.target.value,
                    })}
                  />
                </td>
                <td>
                  <span className="row" style={{ gap: 4 }}>
                    {t.status === "pending" && (
                      <button onClick={() => void onClaim(t)}>认领</button>
                    )}
                    {t.status !== "finalized" && (
                      <button onClick={() => void onSubmit(t, "accepted")}>提交框</button>
                    )}
                    {t.status === "awaiting_arbitration" && (
                      <button onClick={() => void onSubmit(t, "adjudicated", "arbiter")}>仲裁</button>
                    )}
                    {t.status === "finalized" && <span className="muted">不可改</span>}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {tasks && tasks.length === 0 && (
        <p className="muted">审核队列为空；.review_queue 真实队列接入见 U4-3。</p>
      )}
    </>
  );
}

export default function Assets() {
  const [summary, setSummary] = useState<AssetsSummary | null>(null);
  const [rows, setRows] = useState<AssetRow[]>([]);
  const [count, setCount] = useState(0);
  const [sourceId, setSourceId] = useState("");
  const [offset, setOffset] = useState(0);
  const [sources, setSources] = useState<string[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, list] = await Promise.all([
        fetchAssetsSummary(),
        fetchAssetsList({
          source_id: sourceId || undefined, limit: PAGE, offset,
        }),
      ]);
      setSummary(s);
      setRows(list.items);
      setCount(list.count);
      setSources(s.sources);
      setErr("");
    } catch (e) {
      setErr(String(e));
    }
  }, [sourceId, offset]);

  useEffect(() => { void load(); }, [load]);

  return (
    <section>
      <h2>数据资产（真实台账）</h2>
      {err && <p className="degraded">加载失败：{err}</p>}
      {!summary && !err && <p className="muted">加载中…</p>}
      {summary && (
        <>
          <div className="cards">
            <div className="card"><div className="num">{summary.total_refs.toLocaleString()}</div><div className="muted">来源引用总数（含重复）</div></div>
            <div className="card"><div className="num">{summary.unique_sha.toLocaleString()}</div><div className="muted">SHA 唯一照片数</div></div>
            <div className="card"><div className="num">{summary.exact_dup_groups.toLocaleString()}</div><div className="muted">精确重复组</div></div>
            <div className="card"><div className="num">{summary.purposes.eval_frozen?.toLocaleString() ?? 0}</div><div className="muted">评估冻结</div></div>
            <div className="card"><div className="num">{summary.purposes.to_label?.toLocaleString() ?? 0}</div><div className="muted">待标注</div></div>
          </div>
          <p className="muted">
            台账为追加式不可变（source_asset_inventory_v1）；
            冻结→训练泄漏 {summary.leak_frozen_into_training}；
            无用途行 {summary.rows_without_purpose}。
            SHA 唯一数才是唯一照片数，禁止把目录数量相加冒充唯一总数。
          </p>
          <details>
            <summary>用途分布（高级详情）</summary>
            <table className="table">
              <thead><tr><th>用途</th><th>引用数</th></tr></thead>
              <tbody>
                {Object.entries(summary.purposes).map(([k, v]) => (
                  <tr key={k}>
                    <td>{PURPOSE_CN[k] ?? k}</td>
                    <td>{v.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}

      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <label>来源筛选
          <select value={sourceId} onChange={(e) => {
            setSourceId(e.target.value); setOffset(0);
          }}>
            <option value="">全部来源</option>
            {sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <span className="muted">共 {count.toLocaleString()} 条</span>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>来源</th><th>引用</th><th>photo</th><th>SHA</th>
            <th>用途</th><th>登记时间</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.asset_id}>
              <td>{r.source_id}</td>
              <td className="muted" style={{ maxWidth: 320, overflowWrap: "anywhere" }}>{r.source_uri}</td>
              <td>{r.photo_id}</td>
              <td className="muted">{r.sha256.slice(0, 12)}…</td>
              <td>{r.purposes.map((p) => PURPOSE_CN[p] ?? p).join("、")}</td>
              <td className="muted">{r.registered_at.slice(0, 19)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ gap: 8 }}>
        <button disabled={offset <= 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE))}>上一页</button>
        <span className="muted">
          {offset + 1}–{Math.min(offset + PAGE, count)}
        </span>
        <button disabled={offset + PAGE >= count}
          onClick={() => setOffset(offset + PAGE)}>下一页</button>
      </div>

      <GoldSection />
      <ReviewSection />
    </section>
  );
}
