// ABOSV3 T3：Import Center（全模块共用导入中心）。
// 14 套 CSV/XLSX 模板下载；上传 → dry-run（逐行新增/跳过/冲突/错误）
// → 提交（幂等、证据、审计）。全部真实 API，不硬编码。
import { useCallback, useEffect, useState } from "react";
import { csrfToken } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader, StatusBadge }
  from "../platform/components";

interface TemplateCol {
  field: string; label: string; type: string; required: boolean;
  enum: string[]; example: string; doc: string;
}
interface TemplateView {
  template_id: string; name: string; idempotency: string; note: string;
  columns: TemplateCol[];
}
interface BatchView {
  batch_id: string; template_id: string; filename: string;
  file_format: string; status: string; actor: string; row_count: number;
  dry_run: { plan?: Record<string, number>; rows?: number };
  errors: { row: number; error: string }[];
  commit: { stats?: Record<string, number>; receipts?: any[] };
  created_at: string;
}

async function api(path: string, opts?: RequestInit) {
  const r = await fetch(`/api/v1${path}`, opts);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(`${d.detail ?? path}（HTTP ${r.status}）`);
  }
  return r.json();
}
async function apiPost(path: string) {
  const headers: Record<string, string> =
    { "content-type": "application/json" };
  const t = csrfToken();
  if (t) headers["X-CSRF-Token"] = t;
  return api(path, { method: "POST", headers, body: "{}" });
}

export default function ImportCenter() {
  const [templates, setTemplates] = useState<TemplateView[] | null>(null);
  const [batches, setBatches] = useState<BatchView[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selTpl, setSelTpl] = useState("");
  const [detail, setDetail] = useState<BatchView | null>(null);

  const load = useCallback(() => {
    api("/import/templates").then(
      (d) => { setTemplates(d.templates);
        if (!selTpl && d.templates.length) setSelTpl(d.templates[0].template_id);
      }).catch((e) => setErr(String(e.message ?? e)));
    api("/import/batches").then((d) => setBatches(d.batches)).catch(
      (e) => setErr(String(e.message ?? e)));
  }, [selTpl]);
  useEffect(() => { load(); }, []);

  const download = (tid: string, fmt: string) => {
    window.open(`/api/v1/import/templates/${tid}/download?fmt=${fmt}`,
      "_blank");
  };

  const upload = async (file: File) => {
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("template_id", selTpl);
      fd.append("file", file);
      const headers: Record<string, string> = {};
      const t = csrfToken();
      if (t) headers["X-CSRF-Token"] = t;
      const r = await fetch("/api/v1/import/upload",
        { method: "POST", headers, body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail ?? `上传失败 HTTP ${r.status}`);
      setDetail(d.batch);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const act = async (batchId: string, action: "dry-run" | "commit") => {
    setBusy(true); setErr(null);
    try {
      const d = await apiPost(`/import/batches/${batchId}/${action}`);
      setDetail(d.batch); load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const tpl = templates?.find((t) => t.template_id === selTpl);

  return (
    <>
      <PageHeader title="Import Center"
        desc="全模块共用导入：模板下载 → 上传 → dry-run → 逐行错误修复 → 幂等提交（证据与审计留痕）" />
      {err && <ErrorState message={err} onRetry={() => {
        setErr(null); load(); }} />}

      <div className="card">
        <h3>模板（14 套 · CSV/XLSX · 下载后可重新上传解析）</h3>
        {!templates && !err && <Loading text="加载模板…" />}
        {templates && (
          <table className="table">
            <thead><tr><th>模板</th><th>幂等键</th><th>字段</th>
              <th>下载</th></tr></thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.template_id}>
                  <td data-label="模板">{t.name}
                    <div className="meta">{t.template_id}</div></td>
                  <td data-label="幂等键" className="v">
                    {t.idempotency}</td>
                  <td data-label="字段" className="v">
                    {t.columns.length} 个</td>
                  <td data-label="下载">
                    <button className="btn small"
                      onClick={() => download(t.template_id, "csv")}>CSV
                    </button>{" "}
                    <button className="btn small"
                      onClick={() => download(t.template_id, "xlsx")}>XLSX
                    </button></td>
                </tr>))}
            </tbody>
          </table>)}
        {tpl && (
          <details style={{ marginTop: 8 }}>
            <summary className="v">字段说明：{tpl.name}</summary>
            <table className="table">
              <thead><tr><th>字段</th><th>标签</th><th>类型</th>
                <th>必填</th><th>枚举/说明</th><th>样例</th></tr></thead>
              <tbody>
                {tpl.columns.map((c) => (
                  <tr key={c.field}>
                    <td data-label="字段">{c.field}</td>
                    <td data-label="标签">{c.label}</td>
                    <td data-label="类型">{c.type}</td>
                    <td data-label="必填">{c.required ? "是" : "否"}</td>
                    <td data-label="枚举/说明" className="v">
                      {c.enum.length > 1 ? c.enum.slice(1).join("|")
                        : c.doc || "—"}</td>
                    <td data-label="样例" className="v">{c.example}</td>
                  </tr>))}
              </tbody>
            </table>
            {tpl.note && <p className="v" style={{ color: "var(--warn)" }}>
              ⚠ {tpl.note}</p>}
          </details>)}
      </div>

      <div className="card">
        <h3>上传文件</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "center" }}>
          <select value={selTpl} aria-label="选择模板"
            onChange={(e) => setSelTpl(e.target.value)}>
            {(templates ?? []).map((t) => (
              <option key={t.template_id} value={t.template_id}>
                {t.name}（{t.template_id}）</option>))}
          </select>
          <input type="file" accept=".csv,.xlsx" aria-label="选择文件"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
              e.target.value = "";
            }} />
          {busy && <span className="v">处理中…</span>}
        </div>
        <p className="v" style={{ marginTop: 6 }}>
          上传后先预览与 dry-run，不直接写业务表；提交使用自然键幂等。</p>
      </div>

      {detail && (
        <div className="card">
          <h3>批次 {detail.batch_id}（{detail.template_id}）</h3>
          <p className="v">状态：<StatusBadge status={detail.status} />
            {" "}· 行数 {detail.row_count} · {detail.filename}</p>
          {detail.dry_run?.plan && (
            <p className="v">预检：新增 {detail.dry_run.plan.insert ?? 0}
              {" "}· 跳过 {detail.dry_run.plan.skip ?? 0}
              {" "}· 冲突 {detail.dry_run.plan.conflict ?? 0}</p>)}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button className="btn" disabled={busy}
              onClick={() => act(detail.batch_id, "dry-run")}>dry-run
            </button>
            <button className="btn primary" disabled={busy}
              onClick={() => act(detail.batch_id, "commit")}>提交</button>
            <a className="btn"
              href={`/api/v1/import/batches/${detail.batch_id}/errors.csv`}
            >下载错误报告</a>
          </div>
          {detail.errors.length > 0 && (
            <>
              <h3 style={{ marginTop: 12 }}>逐行错误（{detail.errors.length}）
              </h3>
              <table className="table">
                <thead><tr><th>行号</th><th>错误</th></tr></thead>
                <tbody>
                  {detail.errors.slice(0, 30).map((e, i) => (
                    <tr key={i}>
                      <td data-label="行号">{e.row}</td>
                      <td data-label="错误" className="v"
                        style={{ color: "var(--err)" }}>{e.error}</td>
                    </tr>))}
                </tbody>
              </table>
            </>)}
          {detail.commit?.stats && (
            <p className="v" style={{ marginTop: 8 }}>
              提交结果：成功 {detail.commit.stats.inserted ?? 0}
              {" "}· 跳过 {detail.commit.stats.skipped ?? 0}
              {" "}· 失败 {detail.commit.stats.failed ?? 0}</p>)}
          {detail.commit?.receipts?.map((r, i) => (
            r.initial_password_once ? (
              <p key={i} className="v"
                style={{ color: "var(--warn)", marginTop: 4 }}>
                ⚠ 用户 {r.username} 的一次性初始口令：
                <code>{r.initial_password_once}</code>
                （仅显示一次，请尽快修改）</p>
            ) : (
              <p key={i} className="v" style={{ marginTop: 4 }}>
                回执：{JSON.stringify(r).slice(0, 160)}</p>)))}
        </div>)}

      <div className="card">
        <h3>导入批次</h3>
        {!batches && !err && <Loading />}
        {batches && batches.length === 0
          ? <EmptyState title="尚无导入批次" />
          : batches && (
            <table className="table">
              <thead><tr><th>批次</th><th>模板</th><th>状态</th><th>行数</th>
                <th>错误</th><th>时间</th></tr></thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.batch_id} onClick={async () => {
                    const d = await api(`/import/batches/${b.batch_id}`);
                    setDetail(d.batch);
                  }} style={{ cursor: "pointer" }}>
                    <td data-label="批次">{b.batch_id.slice(0, 14)}…</td>
                    <td data-label="模板">{b.template_id}</td>
                    <td data-label="状态"><StatusBadge status={b.status} /></td>
                    <td data-label="行数">{b.row_count}</td>
                    <td data-label="错误">{Array.isArray(b.errors)
                      ? b.errors.length : b.errors}</td>
                    <td data-label="时间" className="v">
                      {String(b.created_at).slice(0, 16)}</td>
                  </tr>))}
              </tbody>
            </table>)}
      </div>
    </>
  );
}
