// ABOSV3 T9：BI 工作台 —— 数据产品/受限公式指标/下钻/ECharts
// Dashboard 画布（真实 API 求值，禁静态假图）。
import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { csrfToken, iamGet, iamPost } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader } from
  "../platform/components";

interface Widget { type: "bar" | "line" | "pie" | "number";
  metric: string; title?: string; }
interface DashboardRow { dashboard_id: string; name: string;
  customer_id: string; widgets: Widget[]; filters: any; status: string; }

function ChartWidget({ widget, customerId, onDrill }: {
  widget: Widget; customerId: string;
  onDrill: (metric: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [value, setValue] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!widget.metric || !customerId) return;
    iamGet(`analytics/metrics/${encodeURIComponent(
      widget.metric)}/evaluate?customer_id=${encodeURIComponent(
      customerId)}`)
      .then((d) => setValue(d.value)).catch(
        (e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [widget.metric, customerId]);

  useEffect(() => {
    if (widget.type === "number" || !ref.current) return;
    if (value === null) return;
    const chart = echarts.init(ref.current);
    const base = { metric: widget.metric, value };
    const option: any = widget.type === "pie" ? {
      title: { text: widget.title ?? widget.metric, left: "center",
        textStyle: { fontSize: 12 } },
      tooltip: { trigger: "item" },
      series: [{ type: "pie", radius: "60%",
        data: [{ name: "当前值", value: base.value }] }],
    } : {
      title: { text: widget.title ?? widget.metric, left: "center",
        textStyle: { fontSize: 12 } },
      tooltip: {},
      xAxis: { type: "category", data: ["当前"] },
      yAxis: { type: "value" },
      series: [{ type: widget.type, data: [base.value] }],
    };
    chart.setOption(option, true);
    chart.on("click", () => onDrill(widget.metric));
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [widget, value]);

  if (err) return <div className="card"
    style={{ marginBottom: 0 }}><ErrorState message={err} /></div>;
  if (widget.type === "number") {
    return (
      <div className="card" style={{ marginBottom: 0, cursor: "pointer" }}
        onClick={() => onDrill(widget.metric)}>
        <h3>{widget.title ?? widget.metric}</h3>
        <p style={{ fontSize: 28, fontWeight: 700 }}>
          {value === null ? "…" : value.toLocaleString()}</p>
        <p className="v">点击数字下钻到事实行</p>
      </div>);
  }
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div ref={ref} style={{ height: 220 }} />
      {value === null && !err && <Loading text="求值中…" />}
    </div>);
}

export default function BIWorkbench() {
  const [metrics, setMetrics] = useState<any[]>([]);
  const [products, setProducts] = useState<any[] | null>(null);
  const [customer, setCustomer] = useState("uat-cust-a");
  const [dashboards, setDashboards] = useState<DashboardRow[]>([]);
  const [selDash, setSelDash] = useState<string>("");
  const [drill, setDrill] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [formula, setFormula] = useState({ metric_id: "", name: "",
    formula: "" });
  const [newWidget, setNewWidget] = useState<Widget>(
    { type: "bar", metric: "" });

  const load = useCallback(() => {
    iamGet("analytics/metrics").then(
      (d) => setMetrics(d.metrics)).catch(
      (e) => setErr(String(e.message ?? e)));
    iamGet("analytics/data-products").then(
      (d) => setProducts(d.products)).catch(() => { });
    iamGet("analytics/dashboards").then(
      (d) => setDashboards(d.dashboards)).catch(() => { });
  }, []);
  useEffect(() => { load(); }, [load]);

  const cur = dashboards.find((d) => d.dashboard_id === selDash);

  const saveDashboard = async () => {
    if (!cur) return;
    try {
      const headers: Record<string, string> =
        { "content-type": "application/json" };
      const t = csrfToken();
      if (t) headers["X-CSRF-Token"] = t;
      const r = await fetch(
        `/api/v1/analytics/dashboards/${cur.dashboard_id}`, {
          method: "PUT", headers,
          body: JSON.stringify({ name: cur.name,
            customer_id: customer, widgets: cur.widgets,
            filters: {} }),
        });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail ?? `保存失败 HTTP ${r.status}`);
      }
      setMsg("看板已保存");
      load();
    } catch (e) { setErr(String((e as Error).message ?? e)); }
  };

  return (
    <>
      <PageHeader title="BI 工作台（指标/公式/画布/下钻）"
        desc="注册制指标 + 受限公式 DSL（禁任意 SQL）+ ECharts 画布；每个数字可下钻到事实行" />
      {msg && <div className="banner banner-info">{msg}</div>}
      {err && <ErrorState message={err} onRetry={() => setErr(null)} />}

      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "center" }}>
          <label className="v">客户筛选</label>
          <input value={customer} aria-label="客户筛选"
            onChange={(e) => setCustomer(e.target.value)} />
          <select value={selDash} aria-label="选择看板"
            onChange={(e) => setSelDash(e.target.value)}>
            <option value="">选择看板…</option>
            {dashboards.map((d) => (
              <option key={d.dashboard_id} value={d.dashboard_id}>
                {d.name}（{d.status}）</option>))}
          </select>
          <button className="btn" onClick={async () => {
            try {
              const r = await iamPost("analytics/dashboards", {
                name: `看板 ${new Date().toLocaleString()}`,
                customer_id: customer, widgets: [], filters: {} });
              setMsg(`已创建 ${r.dashboard_id}`); load();
              setSelDash(r.dashboard_id);
            } catch (e) { setErr(String((e as Error).message ?? e)); }
          }}>新建看板</button>
          {cur && <>
            <select value={newWidget.type} aria-label="图表类型"
              onChange={(e) => setNewWidget({ ...newWidget,
                type: e.target.value as any })}>
              <option value="bar">柱状图</option>
              <option value="line">折线图</option>
              <option value="pie">饼图</option>
              <option value="number">数字卡</option>
            </select>
            <select value={newWidget.metric} aria-label="指标"
              onChange={(e) => setNewWidget({ ...newWidget,
                metric: e.target.value })}>
              <option value="">选择指标…</option>
              {metrics.map((m) => (
                <option key={m.metric_id} value={m.metric_id}>
                  {m.name}（{m.metric_id}）</option>))}
            </select>
            <button className="btn primary" disabled={!newWidget.metric}
              onClick={() => {
                const upd = { ...cur, widgets: [...cur.widgets,
                  { ...newWidget, title: newWidget.metric }] };
                setDashboards((ds) => ds.map((d) =>
                  d.dashboard_id === cur.dashboard_id ? upd : d));
              }}>添加图表</button>
            <button className="btn" onClick={saveDashboard}>保存看板
            </button>
          </>}
        </div>
      </div>

      {cur && (
        <div className="grid" style={{ gridTemplateColumns:
          "repeat(auto-fit, minmax(320px, 1fr))" }}>
          {cur.widgets.length === 0
            ? <EmptyState title="看板为空：选择指标并添加图表" />
            : cur.widgets.map((w, i) => (
              <div key={i} style={{ position: "relative" }}>
                <button className="btn small danger"
                  style={{ position: "absolute", right: 8, top: 8,
                    zIndex: 2 }}
                  onClick={() => setDashboards((ds) => ds.map((d) =>
                    d.dashboard_id === cur.dashboard_id ? { ...d,
                      widgets: d.widgets.filter((_, j) => j !== i) }
                      : d))}>×</button>
                <ChartWidget widget={w} customerId={customer}
                  onDrill={(metric) => iamGet(
                    `analytics/metrics/${encodeURIComponent(
                      metric)}/drilldown?customer_id=${
                      encodeURIComponent(customer)}`)
                    .then(setDrill).catch(
                      (e) => setErr(String(e.message ?? e)))} />
              </div>))}
        </div>)}

      {drill && (
        <div className="card">
          <h3>下钻：{drill.metric_id}（{drill.entity}，
            {drill.rows.length} 行）</h3>
          <table className="table">
            <thead><tr>
              {Object.keys(drill.rows[0] ?? {}).slice(0, 6).map(
                (k) => <th key={k}>{k}</th>)}</tr></thead>
            <tbody>
              {drill.rows.slice(0, 10).map((r: any, i: number) => (
                <tr key={i}>
                  {Object.keys(r).slice(0, 6).map((k) => (
                    <td key={k} data-label={k} className="v">
                      {typeof r[k] === "object"
                        ? JSON.stringify(r[k]).slice(0, 40)
                        : String(r[k]).slice(0, 40)}</td>))}
                </tr>))}
            </tbody>
          </table>
        </div>)}

      <div className="grid" style={{ gridTemplateColumns:
        "repeat(auto-fit, minmax(340px, 1fr))" }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>指标目录（注册制 · 禁任意 SQL）</h3>
          <table className="table">
            <thead><tr><th>指标</th><th>来源</th></tr></thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.metric_id}>
                  <td data-label="指标">{m.name}
                    <div className="meta">{m.metric_id}</div></td>
                  <td data-label="来源" className="v">
                    {m.definition?.source === "computed"
                      ? `公式：${m.definition.formula}`
                      : m.definition?.source}</td>
                </tr>))}
            </tbody>
          </table>
          <h3 style={{ marginTop: 10 }}>创建计算指标（受限公式）</h3>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <input placeholder="metric_id" value={formula.metric_id}
              aria-label="指标ID" onChange={(e) => setFormula(
                { ...formula, metric_id: e.target.value })} />
            <input placeholder="名称" value={formula.name}
              aria-label="指标名称" onChange={(e) => setFormula(
                { ...formula, name: e.target.value })} />
            <input style={{ flex: 1, minWidth: 180 }}
              placeholder="公式，如 survey.submitted * 2"
              value={formula.formula} aria-label="公式"
              onChange={(e) => setFormula(
                { ...formula, formula: e.target.value })} />
            <button className="btn primary" onClick={async () => {
              try {
                await iamPost("analytics/metrics/computed", formula);
                setMsg("计算指标已创建"); load();
              } catch (e) {
                setMsg(`创建失败：${e instanceof Error ? e.message : e}`);
              }
            }}>创建</button>
          </div>
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <h3>数据产品与血缘</h3>
          {!products ? <Loading /> : (
            <table className="table">
              <thead><tr><th>产品</th><th>行数</th><th>血缘</th></tr></thead>
              <tbody>
                {products.map((p) => (
                  <tr key={p.product}>
                    <td data-label="产品">{p.product}</td>
                    <td data-label="行数">{p.rows}</td>
                    <td data-label="血缘" className="v">{p.lineage}</td>
                  </tr>))}
              </tbody>
            </table>)}
        </div>
      </div>
    </>
  );
}
