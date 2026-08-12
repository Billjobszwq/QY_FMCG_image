// ABOSV3 T10：客户级 Usage 工作台（汇总/趋势/下钻/预算/导出）。
import { useCallback, useEffect, useState } from "react";
import { iamGet } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader } from
  "../platform/components";

export default function UsageWorkbench() {
  const [customer, setCustomer] = useState("uat-cust-a");
  const [summary, setSummary] = useState<any | null>(null);
  const [rows, setRows] = useState<any[] | null>(null);
  const [budgets, setBudgets] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!customer) return;
    iamGet(`usage/summary?customer_id=${encodeURIComponent(customer)}`)
      .then(setSummary).catch(
        (e) => setErr(e instanceof Error ? e.message : String(e)));
    iamGet(`usage/rows?customer_id=${encodeURIComponent(customer)}&limit=50`)
      .then((d) => setRows(d.rows)).catch(() => setRows([]));
    iamGet(`usage/budgets?customer_id=${encodeURIComponent(customer)}`)
      .then((d) => setBudgets(d.budgets)).catch(() => setBudgets([]));
  }, [customer]);
  useEffect(() => { load(); }, [load]);

  return (
    <>
      <PageHeader title="客户 Usage 工作台"
        desc="不可变 Usage 账本：按客户/项目/单位统计；每行下钻 run/证据；趋势/异常/预算/CSV 导出" />
      {err && <ErrorState message={err} onRetry={() => setErr(null)} />}
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "center" }}>
          <label className="v">客户</label>
          <input value={customer} aria-label="客户"
            onChange={(e) => setCustomer(e.target.value)} />
          <button className="btn" onClick={load}>刷新</button>
          <a className="btn"
            href={`/api/v1/usage/export.csv?customer_id=${
              encodeURIComponent(customer)}`}>导出 CSV</a>
        </div>
      </div>

      {!summary && !err && <Loading text="加载 Usage…" />}
      {summary && (
        <div className="grid" style={{ gridTemplateColumns:
          "repeat(auto-fit, minmax(300px, 1fr))" }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>按单位汇总</h3>
            {summary.by_unit.length === 0
              ? <EmptyState title="该客户暂无 Usage" />
              : (
                <table className="table">
                  <thead><tr><th>单位</th><th>总量</th><th>事件数</th>
                  </tr></thead>
                  <tbody>
                    {summary.by_unit.map((u: any) => (
                      <tr key={u.unit}>
                        <td data-label="单位">{u.unit}</td>
                        <td data-label="总量">
                          {Number(u.total).toLocaleString()}</td>
                        <td data-label="事件数">{u.n}</td>
                      </tr>))}
                  </tbody>
                </table>)}
            <p className="v" style={{ marginTop: 8 }}>
              未归属事件：{summary.unattributed} · {summary.note}</p>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>按日趋势（近 30 天）</h3>
            <table className="table">
              <thead><tr><th>日期</th><th>事件数</th><th>总量</th></tr>
              </thead>
              <tbody>
                {summary.by_date.slice(0, 14).map((d: any) => (
                  <tr key={d.day}>
                    <td data-label="日期">{d.day}</td>
                    <td data-label="事件数">{d.n}</td>
                    <td data-label="总量">
                      {Number(d.total).toLocaleString()}</td>
                  </tr>))}
              </tbody>
            </table>
            {summary.anomalies.length > 0 && (
              <div className="banner banner-warn"
                style={{ marginTop: 8 }}>
                异常（口径 {summary.anomalies[0].rule}）：
                {summary.anomalies.map((a: any, i: number) => (
                  <span key={i}> {a.day}（{a.count} vs 均值
                    {a.avg}）</span>))}
              </div>)}
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>项目预算（口径：事件计数）</h3>
            {!budgets ? <Loading /> : budgets.length === 0
              ? <EmptyState title="无项目预算" />
              : (
                <table className="table">
                  <thead><tr><th>项目</th><th>预算</th><th>事件数</th>
                  </tr></thead>
                  <tbody>
                    {budgets.map((b: any) => (
                      <tr key={b.project_id}>
                        <td data-label="项目">{b.name}</td>
                        <td data-label="预算">
                          {b.budget_total ?? "—"}</td>
                        <td data-label="事件数">{b.usage_events}</td>
                      </tr>))}
                  </tbody>
                </table>)}
          </div>
        </div>)}

      <div className="card">
        <h3>明细（点击行查看 run/证据关联）</h3>
        {!rows ? <Loading /> : rows.length === 0
          ? <EmptyState title="无明细" />
          : (
            <table className="table">
              <thead><tr><th>时间</th><th>单位</th><th>数量</th>
                <th>run</th><th>profile</th><th>证据</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.usage_id}>
                    <td data-label="时间" className="v">
                      {String(r.occurred_at).slice(0, 16)}</td>
                    <td data-label="单位">{r.unit}</td>
                    <td data-label="数量">
                      {Number(r.quantity).toLocaleString()}</td>
                    <td data-label="run" className="v">
                      {r.run_id ? `${String(r.run_id).slice(0, 12)}…（${
                        r.run_status ?? "?"}）` : "—"}</td>
                    <td data-label="profile" className="v">
                      {r.profile_id || "—"}</td>
                    <td data-label="证据" className="v">
                      {r.source_evidence || r.evidence_bundle_id || "—"}
                    </td>
                  </tr>))}
              </tbody>
            </table>)}
      </div>
    </>
  );
}
