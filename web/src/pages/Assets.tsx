import { useCallback, useEffect, useState } from "react";
import {
  AssetRow, AssetsSummary, fetchAssetsList, fetchAssetsSummary,
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
    </section>
  );
}
