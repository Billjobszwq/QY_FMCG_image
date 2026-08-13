// ABOSV3 T3 + OSV5：Import Center（全模块共用导入中心）。
// OSV5（指令第六节/P1-001）：批次列表显示 文件名/模板/操作人/客户范围/
// data_scope/Test Run/状态/行数/时间；四视图（运营/我的/历史/隔离）；
// 详情为显式 DTO（无原始 payload），原始预览需授权（preview 端点）。
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
interface CustomerScope {
  customer_id: string; project_id: string;
  authorization_decision: string;
}
interface AdjudicationView {
  batch_id?: string; state: string; version: number;
  target_test_run_id?: string; revision_batch_id?: string;
  requested_by?: string; approved_by?: string; reason?: string;
}
interface BatchView {
  batch_id: string; template_id: string; filename: string;
  file_format: string; status: string; actor: string; row_count: number;
  data_scope: string; test_run_id: string; visibility?: string;
  archived_at?: string; customer_scopes: CustomerScope[];
  dry_run?: { plan?: Record<string, number>; rows?: number };
  errors: { row: number; error: string }[];
  commit?: { stats?: Record<string, number>; receipts?: any[] };
  adjudication?: AdjudicationView;
  is_global_template?: boolean;
  created_at: string;
}

const VIEWS = [
  { key: "operational", label: "运营导入" },
  { key: "mine", label: "我的批次" },
  { key: "history", label: "Test Run / 历史证据" },
  { key: "quarantine", label: "隔离待处理" },
] as const;

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
  const [view, setView] = useState<string>("operational");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selTpl, setSelTpl] = useState("");
  const [detail, setDetail] = useState<BatchView | null>(null);
  const [adjReason, setAdjReason] = useState("");
  const [adjTestRun, setAdjTestRun] = useState("");

  const load = useCallback((v: string) => {
    api("/import/templates").then(
      (d) => { setTemplates(d.templates);
        if (!selTpl && d.templates.length) setSelTpl(d.templates[0].template_id);
      }).catch((e) => setErr(String(e.message ?? e)));
    const qs = v === "history" ? "?view=history&include_fixture=1"
      : `?view=${v}`;
    api(`/import/batches${qs}`).then((d) => setBatches(d.batches))
      .catch((e) => { setBatches([]); setErr(String(e.message ?? e)); });
  }, [selTpl]);
  useEffect(() => { load(view); }, [view]);

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
      load(view);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const act = async (batchId: string, action: "dry-run" | "commit") => {
    setBusy(true); setErr(null);
    try {
      const d = await apiPost(`/import/batches/${batchId}/${action}`);
      setDetail(d.batch); load(view);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  // OSV51 C-3：隔离区人工裁决（状态机 + 双人审批，后端 CAS 幂等）
  const adjudicate = async (action: string,
    extra?: Record<string, string>) => {
    if (!detail) return;
    setBusy(true); setErr(null);
    try {
      const headers: Record<string, string> =
        { "content-type": "application/json" };
      const t = csrfToken();
      if (t) headers["X-CSRF-Token"] = t;
      const r = await fetch(
        `/api/v1/import/batches/${detail.batch_id}/adjudication`,
        { method: "POST", headers, body: JSON.stringify(
          { action, reason: adjReason, ...extra }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail ?? `裁决失败 HTTP ${r.status}`);
      const dd = await api(`/import/batches/${detail.batch_id}`);
      setDetail(dd.batch); load(view);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const tpl = templates?.find((t) => t.template_id === selTpl);

  return (
    <>
      <PageHeader title="Import Center"
        desc="全模块共用导入：模板下载 → 上传 → dry-run → 逐行错误修复 → 幂等提交；批次携带作用域/Test Run/客户授权（证据与审计留痕）" />
      {err && <ErrorState message={err} onRetry={() => {
        setErr(null); load(view); }} />}

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
        <h3>上传文件（运营导入）</h3>
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
          上传后先预览与 dry-run，不直接写业务表；提交使用自然键幂等。
          UAT/Test Run 导入必须经受信路径显式携带 test_run_id。</p>
      </div>

      {detail && (
        <div className="card">
          <h3>批次 {detail.filename}（{detail.template_id}）</h3>
          <p className="v">状态：<StatusBadge status={detail.status} />
            {" "}· 作用域：<code data-testid="batch-scope">
              {detail.data_scope}</code>
            {detail.test_run_id ? <> · Test Run：<code
              data-testid="batch-test-run">{detail.test_run_id}</code>
            </> : null}
            {" "}· 行数 {detail.row_count} · 操作人 {detail.actor}</p>
          {detail.customer_scopes?.length > 0 && (
            <p className="v">客户范围：{detail.customer_scopes.map(
              (c) => `${c.customer_id}（${c.authorization_decision}）`)
              .join("；")}</p>)}
          {detail.dry_run?.plan && (
            <p className="v">预检：新增 {detail.dry_run.plan.insert ?? 0}
              {" "}· 跳过 {detail.dry_run.plan.skip ?? 0}
              {" "}· 冲突 {detail.dry_run.plan.conflict ?? 0}</p>)}
          {(() => {
            // OSV51 C-1：隔离/归档/历史批次写冻结——不渲染误导性提交按钮
            const writable = !(detail.data_scope === "quarantine"
              || detail.data_scope === "archived"
              || detail.visibility === "history");
            return writable ? (
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="btn" disabled={busy}
                  onClick={() => act(detail.batch_id, "dry-run")}>dry-run
                </button>
                <button className="btn primary" disabled={busy}
                  onClick={() => act(detail.batch_id, "commit")}>提交
                </button>
                <a className="btn"
                  href={`/api/v1/import/batches/${detail.batch_id}/errors.csv`}
                >下载错误报告</a>
              </div>
            ) : (
              <div style={{ marginTop: 8 }}>
                <p className="v" data-testid="batch-write-frozen"
                  style={{ color: "var(--warn)", border:
                    "1px solid var(--warn)", borderRadius: 6,
                    padding: "6px 10px" }}>
                  ⚠ 该批次作用域为 <code>{detail.data_scope}</code>
                  {detail.visibility === "history" ? "（已归档历史）" : ""}
                  ，已写冻结：不得执行 dry-run/提交。
                  {detail.data_scope === "quarantine"
                    ? "隔离批次不可执行 dry-run/提交，请走裁决流程。"
                    : ""}
                </p>
                <a className="btn"
                  href={`/api/v1/import/batches/${detail.batch_id}/errors.csv`}
                >下载错误报告</a>
              </div>
            );
          })()}
          {detail.data_scope === "quarantine" && (() => {
            // OSV51 C-3：隔离区人工裁决面板（状态机显隐 + 双人审批）
            const adj: AdjudicationView = detail.adjudication
              ?? { state: "quarantined", version: 0 };
            const st = adj.state;
            const can = (a: string) => (
              (a === "approve_release" || a === "reject_release")
                ? st === "release_requested"
                : (st === "quarantined" || st === "retained_for_evidence"
                  || (a === "retain" && st === "release_requested")));
            return (
              <div style={{ marginTop: 10, border: "1px solid var(--line)",
                borderRadius: 8, padding: 10 }}
                data-testid="quarantine-adjudication">
                <h3 style={{ marginTop: 0 }}>隔离区裁决
                  <code style={{ marginLeft: 8 }}
                    data-testid="adjudication-state">{st}</code>
                  <span className="v" style={{ marginLeft: 8 }}>
                    version {adj.version}
                    {adj.requested_by ? ` · 申请人 ${adj.requested_by}`
                      : ""}
                    {adj.approved_by ? ` · 审批人 ${adj.approved_by}` : ""}
                  </span></h3>
                {adj.revision_batch_id ? (
                  <p className="v">修订批次：
                    <code>{adj.revision_batch_id}</code></p>) : null}
                {(st === "quarantined" || st === "retained_for_evidence"
                  || st === "release_requested") && (
                  <>
                    <div style={{ display: "flex", gap: 8,
                      flexWrap: "wrap", alignItems: "center" }}>
                      <input className="v" placeholder="裁决理由（审计留痕）"
                        aria-label="裁决理由" value={adjReason}
                        onChange={(e) => setAdjReason(e.target.value)}
                        style={{ minWidth: 220 }} />
                      {can("retain") && (
                        <button className="btn small" disabled={busy}
                          onClick={() => adjudicate("retain")}>
                          继续隔离留证</button>)}
                      {can("retain") && (
                        <button className="btn small" disabled={busy}
                          onClick={() => {
                            if (window.confirm("确认软作废该隔离批次？"
                              + "（不删除原始证据，仅标记）"))
                              adjudicate("soft_discard");
                          }}>软作废</button>)}
                      {can("retain") && (
                        <button className="btn small" disabled={busy}
                          onClick={() => adjudicate("request_release")}>
                          申请转正式</button>)}
                    </div>
                    {can("retain") && (
                      <div style={{ display: "flex", gap: 8, marginTop: 6,
                        flexWrap: "wrap", alignItems: "center" }}>
                        <input className="v" placeholder="目标 Test Run ID"
                          aria-label="目标 Test Run" value={adjTestRun}
                          onChange={(e) => setAdjTestRun(e.target.value)} />
                        <button className="btn small" disabled={busy
                          || !adjTestRun.trim()}
                          onClick={() => adjudicate("bind_test_run",
                            { target_test_run_id:
                              adjTestRun.trim() })}>
                          绑定 Test Run</button>
                      </div>)}
                  </>)}
                {st === "release_requested" && (
                  <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                    <button className="btn small primary" disabled={busy}
                      onClick={() => {
                        if (window.confirm("批准转正式？将由申请人之外的"
                          + "审批人创建新的运营修订批次。"))
                          adjudicate("approve_release");
                      }}>批准转正式（双人审批）</button>
                    <button className="btn small" disabled={busy}
                      onClick={() => adjudicate("reject_release")}>
                      拒绝申请</button>
                  </div>)}
                {(st === "soft_discarded" || st === "release_approved"
                  || st === "bound_to_test_run"
                  || st === "superseded_by_new_batch") && (
                  <p className="v">当前为终态 {st}；如需变更请走新的
                    裁决申请。</p>)}
              </div>);
          })()}
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
            r.initial_password_once && r.initial_password_once
              !== "[REDACTED]" ? (
              <p key={i} className="v"
                style={{ color: "var(--warn)", marginTop: 4 }}>
                ⚠ 用户 {r.username} 的一次性初始口令：
                <code>{r.initial_password_once}</code>
                （仅在提交成功的当次响应中显示；系统不落库明文，
                刷新或重读详情后不再可见，请尽快修改）</p>
            ) : (
              <p key={i} className="v" style={{ marginTop: 4 }}>
                回执：{JSON.stringify(r).slice(0, 160)}</p>)))}
        </div>)}

      <div className="card">
        <h3>导入批次</h3>
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}
          role="tablist" aria-label="批次视图">
          {VIEWS.map((v) => (
            <button key={v.key} role="tab"
              aria-selected={view === v.key}
              className={`btn small${view === v.key ? " primary" : ""}`}
              onClick={() => { setView(v.key); setErr(null); }}>
              {v.label}</button>))}
        </div>
        {!batches && !err && <Loading />}
        {batches && batches.length === 0
          ? <EmptyState title={view === "operational"
            ? "运营面无导入批次" : "该视图暂无批次（或无权查看）"} />
          : batches && (
            <table className="table">
              <thead><tr><th>文件名</th><th>模板</th><th>操作人</th>
                <th>客户范围</th><th>作用域</th><th>Test Run</th>
                <th>状态</th><th>行数</th><th>时间</th></tr></thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.batch_id} data-batch-id={b.batch_id}
                    onClick={async () => {
                      try {
                        const d = await api(
                          `/import/batches/${b.batch_id}`);
                        setDetail(d.batch);
                      } catch (e) {
                        setErr(String((e as Error).message ?? e));
                      }
                    }} style={{ cursor: "pointer" }}>
                    <td data-label="文件名">{b.filename}
                      <div className="meta">{b.batch_id}</div></td>
                    <td data-label="模板">{b.template_id}</td>
                    <td data-label="操作人">{b.actor}</td>
                    <td data-label="客户范围" className="v"
                      data-testid={`cust-scope-${b.batch_id}`}>
                      {(b.customer_scopes ?? []).map(
                        (c) => c.customer_id).join("；")
                        || (b.is_global_template
                          ? "全局"
                          : b.data_scope === "quarantine"
                            ? "未绑定/待裁决（隔离）"
                            : "未绑定/待裁决")}</td>
                    <td data-label="作用域" data-scope={b.data_scope}>
                      <code>{b.data_scope}</code></td>
                    <td data-label="Test Run" className="v">
                      {b.test_run_id || "—"}</td>
                    <td data-label="状态"><StatusBadge status={b.status} />
                    </td>
                    <td data-label="行数">{b.row_count}</td>
                    <td data-label="时间" className="v">
                      {String(b.created_at).slice(0, 16)}</td>
                  </tr>))}
              </tbody>
            </table>)}
      </div>
    </>
  );
}
