import { useCallback, useEffect, useState } from "react";
import {
  AssetRow, AssetsSummary, buildGoldQueue, csrfToken, fetchAssetsList,
  fetchAssetsSummary, fetchGoldConfusion, fetchGoldStatus, GoldStatusBody,
  submitGoldVerdict,
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
    </section>
  );
}
