// ABOSV2 Phase F：财务与结算（合同与价目卡 / 账单与结算）。
// 账单仅从 immutable Usage 生成；行可下钻 usage/run/node/证据；
// 调整 append-only；已开票金额不随新价格变动。
import { useState } from "react";
import { useEffect } from "react";
import { iamGet, iamPost } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader }
  from "../platform/components";
import { CustomerPicker, useOperationalCustomer } from
  "../platform/useOperationalCustomer";

function useLoad<T>(path: string | null): {
  data: T | null; err: string | null; reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    iamGet(path).then(setData).catch(
      (e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [path, tick]);
  return { data, err, reload: () => { setErr(null); setTick(t => t + 1); } };
}

// ---- 1. 合同与价目卡 ----
export function FinanceContracts() {
  const { customer: cid, setCustomer: setCid, options } =
    useOperationalCustomer();
  const contracts = useLoad<any>(
    cid ? `finance/contracts?customer_id=${cid}` : null);
  const rc = useLoad<any>("finance/rate-cards/rc_standard");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="合同与价目卡"
        desc="rate card 版本化；价格变更仅限平台角色；历史账单不重算" />
      <div className="card">
        <div style={{ display: "flex", gap: 8 }}>
          <CustomerPicker customer={cid} setCustomer={setCid}
            options={options} ariaLabel="客户" />
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("finance/contracts",
                { customer_id: cid, kind: "usage",
                  rate_card_id: "rc_standard" });
              setMsg("合同已创建"); contracts.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>新建合同</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {rc.data && (
        <div className="card">
          <h3>价目卡 rc_standard（v{rc.data.rate_card.version}）</h3>
          <table className="table">
            <thead><tr><th>单位</th><th>单价</th></tr></thead>
            <tbody>
              {rc.data.rate_card.lines.map((l: any) => (
                <tr key={l.unit}>
                  <td data-label="单位" className="v">{l.unit}</td>
                  <td data-label="单价">{l.price}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="v" style={{ fontSize: 11 }}>
            新版本价目只影响其后生成的账单；已开票金额绑定开票时版本。</p>
        </div>
      )}
      {contracts.err && <ErrorState message={contracts.err}
        onRetry={contracts.reload} />}
      {contracts.data && (contracts.data.contracts.length === 0
        ? <EmptyState title="该客户暂无合同" />
        : (
          <table className="table">
            <thead><tr><th>contract_id</th><th>类型</th><th>价目卡</th>
              <th>状态</th></tr></thead>
            <tbody>
              {contracts.data.contracts.map((c: any) => (
                <tr key={c.contract_id}>
                  <td data-label="contract_id" className="v">
                    {c.contract_id}</td>
                  <td data-label="类型">{c.kind}</td>
                  <td data-label="价目卡">{c.rate_card_id}</td>
                  <td data-label="状态">{c.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
    </>
  );
}

// ---- 2. 账单与结算 ----
export function FinanceInvoices() {
  const { customer: cid, setCustomer: setCid, options } =
    useOperationalCustomer();
  const [period, setPeriod] = useState(() =>
    new Date().toISOString().slice(0, 7));
  const invs = useLoad<any>(
    cid ? `finance/invoices?customer_id=${cid}` : null);
  const [detail, setDetail] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="账单与结算"
        desc="仅从 immutable Usage 生成；每行下钻 usage/run/node/证据；调整 append-only" />
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <CustomerPicker customer={cid} setCustomer={setCid}
            options={options} ariaLabel="客户" />
          <input placeholder="期间 YYYY-MM" aria-label="期间"
            value={period}
            onChange={(e) => setPeriod(e.target.value)} />
          <button className="btn small primary" onClick={async () => {
            try {
              const out = await iamPost("finance/invoices/generate",
                { customer_id: cid, period });
              setMsg(`账单草稿已生成：${out.invoice.invoice_id} ·
                总额 ${out.invoice.total}`);
              invs.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>生成账单（来自 Usage）</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {invs.err && <ErrorState message={invs.err} onRetry={invs.reload} />}
      {!invs.data && !invs.err && <Loading />}
      {invs.data && (invs.data.invoices.length === 0
        ? <EmptyState title="该客户暂无账单" next="先生成 Usage 再开账单" />
        : invs.data.invoices.map((inv: any) => (
          <div className="card" key={inv.invoice_id}>
            <h3>{inv.invoice_id} <span className="v">{inv.period} ·
              {inv.status} · total {inv.total} · net {inv.net_total} ·
              价目 v{inv.rate_card_version}</span></h3>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button className="btn small" onClick={async () => {
                try {
                  const out = await iamGet(
                    `finance/invoices/${inv.invoice_id}`);
                  setDetail(out.invoice);
                } catch (e) { setMsg(`详情失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>下钻明细</button>
              <button className="btn small primary" onClick={async () => {
                try {
                  await iamPost(`finance/invoices/${inv.invoice_id
                    }/issue`, {});
                  setMsg("已开票"); invs.reload();
                } catch (e) { setMsg(`开票失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>开票</button>
              <button className="btn small" onClick={async () => {
                const reason = prompt("调整原因（必填）");
                if (!reason) return;
                try {
                  await iamPost(`finance/invoices/${inv.invoice_id
                    }/adjust`, { kind: "discount", amount: -5, reason });
                  setMsg("调整已追加（append-only）"); invs.reload();
                } catch (e) { setMsg(`调整失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>调整</button>
              <button className="btn small" onClick={async () => {
                try {
                  await iamPost(`finance/invoices/${inv.invoice_id
                    }/settle`, {});
                  setMsg("已结算"); invs.reload();
                } catch (e) { setMsg(`结算失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>结算</button>
            </div>
            {detail && detail.invoice_id === inv.invoice_id && (
              <div style={{ marginTop: 8 }}>
                <table className="table">
                  <thead><tr><th>单位</th><th>数量</th><th>单价</th>
                    <th>金额</th><th>下钻</th></tr></thead>
                  <tbody>
                    {detail.lines.map((l: any) => (
                      <tr key={l.line_id}>
                        <td data-label="单位" className="v">{l.unit}</td>
                        <td data-label="数量">{l.quantity}</td>
                        <td data-label="单价">{l.unit_price}</td>
                        <td data-label="金额">{l.amount}</td>
                        <td data-label="下钻" className="v"
                          style={{ fontSize: 10 }}>
                          {(l.drilldown ?? []).slice(0, 3).map(
                            (d2: any, i: number) => (
                              <span key={i}>
                                {d2.run_id ? `run ${String(d2.run_id
                                  ).slice(0, 12)}… / node ${d2.node
                                  } / ${d2.source_evidence}`
                                  : `订阅 ${d2.period}`}<br /></span>
                            ))}
                          {(l.drilldown ?? []).length > 3
                            ? `… 共 ${l.drilldown.length} 条` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.adjustments.length > 0 && (
                  <p className="v" style={{ fontSize: 11 }}>
                    调整：{detail.adjustments.map((a: any) =>
                      `${a.kind} ${a.amount}（${a.reason}）`)
                      .join("；")}</p>
                )}
              </div>
            )}
          </div>
        )))}
    </>
  );
}
