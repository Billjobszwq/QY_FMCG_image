// ABOSV2 Phase F：分析与 BI（报表与仪表盘 / 异常与追问 / 指标语义层）。
// 数值全部来自注册制指标的实时求值；无假图表；发布须人工批准。
import { useState } from "react";
import { useEffect } from "react";
import { iamGet, iamPost } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader }
  from "../platform/components";

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

// ---- 1. 报表与仪表盘 ----
export function AnalyticsReports() {
  const reps = useLoad<any>("analytics/reports");
  const metrics = useLoad<any>("analytics/metrics");
  const [form, setForm] = useState({ name: "", customer_id: "",
    metrics: [] as string[], nl: "" });
  const [evals, setEvals] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const toggleMetric = (m: string) => setForm((f) => ({
    ...f, metrics: f.metrics.includes(m)
      ? f.metrics.filter((x) => x !== m) : [...f.metrics, m] }));

  return (
    <>
      <PageHeader title="报表与仪表盘"
        desc="注册制指标实时求值（禁任意 SQL）；发布必须人工批准" />
      <div className="card">
        <h3>新建报表（或让 Analytics Agent 生成草稿）</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input placeholder="报表名称" aria-label="报表名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="customer_id" aria-label="客户"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form,
              customer_id: e.target.value })} />
          {(metrics.data?.metrics ?? []).map((m: any) => (
            <label key={m.metric_id} style={{ fontSize: 12 }}>
              <input type="checkbox"
                checked={form.metrics.includes(m.metric_id)}
                onChange={() => toggleMetric(m.metric_id)} />
              {m.name}
            </label>
          ))}
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("analytics/reports", {
                name: form.name, customer_id: form.customer_id,
                metrics: form.metrics, dimensions: ["project"] });
              setMsg("草稿已创建"); reps.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>创建草稿</button>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input style={{ flex: 1 }} placeholder="自然语言：例如 看看识别情况"
            aria-label="自然语言需求" value={form.nl}
            onChange={(e) => setForm({ ...form, nl: e.target.value })} />
          <button className="btn small" disabled={!form.nl.trim()
            || !form.customer_id} onClick={async () => {
            try {
              const out = await iamPost("analytics/agent-draft",
                { text: form.nl, customer_id: form.customer_id });
              setMsg(out.note + (out.draft
                ? `（draft ${out.draft.spec_id}，需人工批准发布）` : ""));
              reps.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>Agent 生成 draft</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {reps.err && <ErrorState message={reps.err} onRetry={reps.reload} />}
      {!reps.data && !reps.err && <Loading />}
      {reps.data && (reps.data.reports.length === 0
        ? <EmptyState title="暂无报表" next="从上方创建或让 Agent 生成草稿" />
        : reps.data.reports.map((r: any) => (
          <div className="card" key={`${r.spec_id}@${r.version}`}>
            <h3>{r.name} <span className="v">{r.spec_id} ·
              v{r.version} · {r.status} · 客户 {r.customer_id}</span></h3>
            <p className="v" style={{ fontSize: 12 }}>
              指标：{r.metrics.join("、")}
              {r.nl_query ? ` · NL：${r.nl_query}` : ""}
              {r.note ? ` · ${r.note}` : ""}</p>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button className="btn small" onClick={async () => {
                try {
                  const ev = await iamGet(
                    `analytics/reports/${r.spec_id}/evaluate`);
                  setEvals((x) => ({ ...x, [r.spec_id]: ev }));
                } catch (e) { setMsg(`评估失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>评估（实时）</button>
              <button className="btn small" onClick={async () => {
                try { await iamPost(`analytics/reports/${r.spec_id
                  }/approve`, {}); setMsg("已批准"); reps.reload(); }
                catch (e) { setMsg(`批准失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>批准（人工）</button>
              <button className="btn small primary" onClick={async () => {
                try { await iamPost(`analytics/reports/${r.spec_id
                  }/publish`, {}); setMsg("已发布"); reps.reload(); }
                catch (e) { setMsg(`发布失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>发布</button>
            </div>
            {evals[r.spec_id] && (
              <div style={{ marginTop: 8 }}>
                {Object.entries(evals[r.spec_id].values ?? {}).map(
                  ([k, v]) => (
                    <p key={k} className="v" style={{ fontSize: 12 }}>
                      {k} = {String(v)}</p>
                  ))}
              </div>
            )}
            {evals[r.spec_id] && Object.keys(
              evals[r.spec_id].breakdown ?? {}).length > 0 && (
              <p className="v" style={{ fontSize: 11, marginTop: 6 }}>
                按项目拆分：{Object.entries(evals[r.spec_id].breakdown)
                  .map(([pid, vals]: [string, any]) => `${pid}(${Object
                    .values(vals).join("/")})`).join("、")}
              </p>
            )}
          </div>
        )))}
    </>
  );
}

// ---- 2. 异常与追问 ----
export function AnalyticsAnomalies() {
  const anos = useLoad<any>("analytics/anomalies");
  const metrics = useLoad<any>("analytics/metrics");
  const [form, setForm] = useState({ metric_id: "survey.avg_score",
    customer_id: "", op: "lt", threshold: "20" });
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="异常与追问"
        desc="异常 → 追问任务 → 回答 → 报表刷新（新版本）" />
      <div className="card">
        <h3>检查异常规则</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <select value={form.metric_id} aria-label="指标"
            onChange={(e) => setForm({ ...form,
              metric_id: e.target.value })}>
            {(metrics.data?.metrics ?? []).map((m: any) => (
              <option key={m.metric_id} value={m.metric_id}>
                {m.name}</option>
            ))}
          </select>
          <input placeholder="customer_id" aria-label="客户"
            value={form.customer_id}
            onChange={(e) => setForm({ ...form,
              customer_id: e.target.value })} />
          <select value={form.op} aria-label="操作符"
            onChange={(e) => setForm({ ...form, op: e.target.value })}>
            <option value="lt">低于</option>
            <option value="gt">高于</option>
            <option value="le">不高于</option>
            <option value="ge">不低于</option>
          </select>
          <input style={{ width: 90 }} aria-label="阈值"
            value={form.threshold}
            onChange={(e) => setForm({ ...form,
              threshold: e.target.value })} />
          <button className="btn small primary" onClick={async () => {
            try {
              const out = await iamPost("analytics/anomalies/check", {
                metric_id: form.metric_id, customer_id: form.customer_id,
                op: form.op, threshold: Number(form.threshold) });
              setMsg(out.hit
                ? `命中：observed=${out.observed}，已创建追问任务`
                : `未命中（observed=${out.observed}）`);
              anos.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>检查</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {anos.err && <ErrorState message={anos.err} onRetry={anos.reload} />}
      {!anos.data && !anos.err && <Loading />}
      {anos.data && (anos.data.anomalies.length === 0
        ? <EmptyState title="暂无异常" />
        : anos.data.anomalies.map((a: any) => (
          <div className="card" key={a.anomaly_id}>
            <h3>{a.metric_id} <span className="v">{a.anomaly_id} ·
              {a.status} · observed={a.observed} ·
              规则 {a.rule.op} {a.threshold}</span></h3>
            {a.status === "open" && (
              <AnswerBox anomalyId={a.anomaly_id}
                onDone={(m) => { setMsg(m); anos.reload(); }} />
            )}
          </div>
        )))}
    </>
  );
}

function AnswerBox({ anomalyId, onDone }: {
  anomalyId: string; onDone: (m: string) => void;
}) {
  const [text, setText] = useState("");
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <input style={{ flex: 1 }} aria-label="追问回答" value={text}
        placeholder="调查结论与处理…"
        onChange={(e) => setText(e.target.value)} />
      <button className="btn small primary" disabled={!text.trim()}
        onClick={async () => {
          try {
            const out = await iamPost(
              `analytics/anomalies/${anomalyId}/answer`,
              { answer: text });
            onDone(out.refreshed_report
              ? `已回答：异常关闭，报表刷新为 v${out.refreshed_report.version
              }（draft，需重新批准发布）`
              : "已回答：异常关闭");
          } catch (e) { onDone(`回答失败：${e instanceof Error
            ? e.message : e}`); }
        }}>回答并刷新报表</button>
    </div>
  );
}

// ---- 3. 指标语义层 ----
export function AnalyticsSemantics() {
  const metrics = useLoad<any>("analytics/metrics");
  return (
    <>
      <PageHeader title="指标语义层"
        desc="Metric 注册表：Agent 与报表只能引用已注册指标（禁止任意 SQL）" />
      {metrics.err && <ErrorState message={metrics.err}
        onRetry={metrics.reload} />}
      {!metrics.data && !metrics.err && <Loading />}
      {metrics.data && (
        <table className="table">
          <thead><tr><th>metric_id</th><th>名称</th><th>来源定义</th>
            </tr></thead>
          <tbody>
            {metrics.data.metrics.map((m: any) => (
              <tr key={m.metric_id}>
                <td data-label="metric_id" className="v">{m.metric_id}</td>
                <td data-label="名称">{m.name}</td>
                <td data-label="来源定义" className="v"
                  style={{ fontSize: 11 }}>
                  {m.definition?.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
