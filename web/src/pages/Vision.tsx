// ABOS T5/T8：智能识别域（首个 Domain Pack）真实二级路由。
// /vision/recognize /vision/tasks /vision/annotation /vision/datasets
// /vision/models /vision/evidence —— 每条独立可深链接。
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  RecognitionProfileRow, RecognitionTaskDetail, RecognitionTaskRow,
  RecognitionTaskView, fetchGoldStatus, fetchRecognitionProfiles,
  fetchRecognitionTaskDetail, fetchRecognitionTasks, fetchReviewStatus,
  recognizeByUrl, uploadRecognitionFiles,
} from "../api";
import {
  DetailDrawer, EmptyState, ErrorState, Loading, PageHeader,
} from "../platform/components";
import Annotation from "./Annotation";
import Assets from "./Assets";
import LabelStudioHub from "./LabelStudioHub";
import Training from "./Training";
import ModelRuntime from "./ModelRuntime";
import type { HealthBody } from "../api";

const ENTRY_CN: Record<string, string> = {
  single_file: "单文件", batch_file: "批量文件", url: "URL",
  api: "API", agent: "Agent",
};
const STATUS_CN: Record<string, string> = {
  completed: "已完成", failed: "失败",
};
const COLORS = ["#c92f2f", "#0b6fd6", "#148a4c", "#b3760a",
  "#7048c8", "#c0366c", "#0d8aa8", "#4d52c9"];

function BoxOverlay({ preview, products }:
  { preview: string; products: any[] }) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  return (
    <div style={{ position: "relative", display: "inline-block",
      maxWidth: "100%" }}>
      <img src={preview} alt="识别结果叠框图" className="rec-img"
        style={{ width: "100%", height: "auto", display: "block",
          borderRadius: 10 }}
        onLoad={(e) => setDim({ w: e.currentTarget.naturalWidth,
          h: e.currentTarget.naturalHeight })} />
      {dim && (
        <svg viewBox={`0 0 ${dim.w} ${dim.h}`}
          style={{ position: "absolute", inset: 0, width: "100%",
            height: "100%" }}>
          {products.map((p, i) => {
            const [x1, y1, x2, y2] = p.box;
            const c = COLORS[i % COLORS.length];
            return (
              <g key={i}>
                <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1}
                  fill="none" stroke={c}
                  strokeWidth={Math.max(2, dim.w / 400)} />
                <text x={x1} y={Math.max(14, y1 - 6)} fill="#fff"
                  stroke={c} strokeWidth={4} paintOrder="stroke"
                  fontSize={Math.max(12, dim.w / 60)} fontWeight={800}>
                  {i + 1}. {p.name || "unknown"}
                  {p.confidence
                    ? ` ${(p.confidence * 100).toFixed(0)}%` : ""}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

// ---- Profile 选择器：选择真正进入识别请求（T7） ----
export function ProfilePicker({ value, onChange }:
  { value: string; onChange: (id: string) => void }) {
  const [ps, setPs] = useState<RecognitionProfileRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetchRecognitionProfiles().then((d) => setPs(d.profiles))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);
  if (err) return <ErrorState message={`Profile 加载失败：${err}`}
    onRetry={() => { setErr(null);
      fetchRecognitionProfiles().then((d) => setPs(d.profiles))
        .catch((e) => setErr(String(e))); }} />;
  if (!ps) return <Loading text="加载识别 Profile…" />;
  return (
    <div className="card">
      <h3>识别 Profile（服务端校验，禁用项无法提交）</h3>
      <div className="grid" role="radiogroup" aria-label="识别 Profile">
        {ps.map((p) => {
          const on = p.status === "enabled";
          const active = value === p.profile_id;
          return (
            <div key={p.profile_id} role="radio" aria-checked={active}
              aria-disabled={!on} tabIndex={on ? 0 : -1}
              aria-pressed={active} className="tile"
              style={{ cursor: on ? "pointer" : "not-allowed" }}
              onClick={() => on && onChange(p.profile_id)}
              onKeyDown={(e) => {
                if (on && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault(); onChange(p.profile_id);
                }
              }}>
              <span className="k">{p.profile_id}</span>
              <span className={`badge ${on ? "ok" : "muted"}`}>
                {on ? "可用" : "禁用"}</span>
              <span className="v">
                {(p.blockers ?? []).join("；")
                  || (p.tags ?? []).join("，")
                  || (p.components ?? []).join(" + ")}</span>
            </div>
          );
        })}
      </div>
      <p className="v" style={{ marginTop: 10 }}>
        当前请求将使用：<b>{value}</b>（随单图/批量/URL 请求提交，
        服务端只接受已注册且启用的 Profile）
      </p>
    </div>
  );
}

// ---- /vision/recognize 即时识别（单图/批量/URL 同源同任务表） ----
export function RecognizeNow({ health }: { health: HealthBody | null }) {
  const [profile, setProfile] = useState("production_legacy");
  const [tier, setTier] = useState("standard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<RecognitionTaskView | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const opts = useMemo(() => ({
    recognition_profile_id: profile, service_tier: tier,
    source: "web" as const,
  }), [profile, tier]);
  const degraded = health && health.status !== "healthy";

  const run = async (fn: () => Promise<RecognitionTaskView>,
                     file?: File) => {
    setBusy(true); setError(null); setView(null);
    setPreview(file ? URL.createObjectURL(file) : null);
    try { setView(await fn()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const singleProducts = useMemo(() => {
    // 单图也走统一任务表；结果图叠框来自 results[0].products
    const r0: any = view?.results?.[0];
    return (r0?.products ?? []) as any[];
  }, [view]);

  return (
    <>
      <PageHeader title="即时识别"
        desc="单图 / 批量 / URL 共用同一识别服务与统一任务历史" />
      {degraded && (
        <div className="banner banner-warn">
          识别服务当前降级（{health?.services?.map((s) =>
            s.status !== "healthy" ? `${s.name}: ${s.status}` : null)
            .filter(Boolean).join("；")}）。可继续提交，失败会诚实返回。
        </div>
      )}
      <ProfilePicker value={profile} onChange={setProfile} />
      <div className="card">
        <h3>服务档位</h3>
        <select value={tier} aria-label="服务档位"
          onChange={(e) => setTier(e.target.value)}>
          <option value="standard">standard（标准 · 当前唯一可用）</option>
          <option value="fast" disabled>
            fast — 未启用（无真实算力/SLA/价格差异）</option>
          <option value="high" disabled>
            high — 未启用（无真实算力/SLA/价格差异）</option>
          <option value="extreme" disabled>
            extreme — 未启用（无真实算力/SLA/价格差异）</option>
        </select>
        <p className="v" style={{ marginTop: 6 }}>
          ABOSV2-P0-004：档位尚未真实路由不同模型/计算/SLA/价格，
          仅 standard 可用；其余档位明确标记未启用，不作为可售选项。
        </p>
      </div>
      {busy && <p className="muted" role="status">识别中…</p>}
      {error && <div className="banner banner-error">识别失败：{error}</div>}

      <div className="card">
        <h3>① 单图识别（写入统一任务历史）</h3>
        <label className="upload"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) run(() => uploadRecognitionFiles([f], opts), f);
          }}>
          <input type="file" accept="image/*" aria-label="上传单张照片"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) run(() => uploadRecognitionFiles([f], opts), f);
            }} />
          拖拽或点击上传货架照片
        </label>
      </div>
      <div className="card">
        <h3>② 批量识别</h3>
        <label className="upload">
          <input type="file" accept="image/*" multiple
            aria-label="批量上传照片"
            onChange={(e) => {
              const fs = e.target.files;
              if (fs && fs.length) {
                run(() => uploadRecognitionFiles(Array.from(fs), opts));
              }
            }} />
          选择多张照片批量识别（上限 32 张）
        </label>
      </div>
      <div className="card">
        <h3>③ URL 识别</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ flex: 1 }} aria-label="图片 URL"
            placeholder="http(s)://…/photo.jpg" value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter"
              && run(() => recognizeByUrl(url.trim(), opts))} />
          <button className="btn primary" disabled={busy || !url.trim()}
            onClick={() => run(() => recognizeByUrl(url.trim(), opts))}>
            识别</button>
        </div>
      </div>

      {view && (
        <div className="card">
          <h3>结果</h3>
          <p className="v">
            <span className="pill-healthy">
              {ENTRY_CN[view.task.entry] ?? view.task.entry}</span>{" "}
            · {view.task.file_count} 个输入 · 检出 {view.task.sku_count} 个
            · 耗时 {view.elapsed_ms} ms
            · profile <code>{view.recognition_profile_id}</code>
            · trace <code>{view.trace_id}</code>
            {view.idempotent_replay && " · 幂等重放"}
          </p>
          {view.errors.length > 0 && (
            <div className="banner banner-warn">
              {view.errors.map((e) => <p key={e} style={{ margin: "2px 0" }}>
                {e}</p>)}
            </div>
          )}
          {preview && singleProducts.length > 0 && (
            <BoxOverlay preview={preview} products={singleProducts} />
          )}
          {preview && singleProducts.length === 0
            && view.task.sku_count === 0 && (
            <div className="banner banner-info">
              0 检出：近景/非货架图或不在 registry 内的商品会诚实返回 0，
              这是预期行为（fail-closed），不是故障。
            </div>
          )}
          <table className="table">
            <thead><tr><th>输入</th><th>检出数</th><th>模型</th></tr></thead>
            <tbody>
              {view.results.map((r, i) => (
                <tr key={i}>
                  <td>{String(r.name ?? "?")}</td>
                  <td>{String(r.count ?? 0)}</td>
                  <td className="v">{String(r.model ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ---- /vision/tasks 任务历史（Web/API/Agent 同源） ----
export function VisionTasks() {
  const [tasks, setTasks] = useState<RecognitionTaskRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  // ABOSV2-P1-005：统一任务详情（真实 API，不伪造）
  const [detail, setDetail] = useState<RecognitionTaskDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  const openDetail = async (taskId: string) => {
    setDetailErr(null);
    try {
      setDetail(await fetchRecognitionTaskDetail(taskId));
    } catch (e) {
      setDetailErr(e instanceof Error ? e.message : String(e));
    }
  };
  const PAGE = 20;
  const reload = useCallback(async () => {
    try {
      const d = await fetchRecognitionTasks({
        limit: PAGE, offset: page * PAGE, status: status || undefined });
      setTasks(d.tasks); setTotal(d.count); setErr(null);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, [page, status]);
  useEffect(() => { reload(); }, [reload]);

  return (
    <>
      <PageHeader title="识别任务"
        desc="Web / API / Agent 三入口同一任务表；按 trace_id 可查证据" />
      <div className="card">
        <div style={{ display: "flex", gap: 8, alignItems: "center",
          marginBottom: 10 }}>
          <select value={status} aria-label="状态筛选"
            onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
            <option value="">全部状态</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
          </select>
          <button className="btn small" disabled={page === 0}
            onClick={() => setPage(page - 1)}>上一页</button>
          <span className="v">共 {total} 条 · 第 {page + 1} 页</span>
          <button className="btn small"
            disabled={!tasks || tasks.length < PAGE}
            onClick={() => setPage(page + 1)}>下一页</button>
          <button className="btn small" onClick={reload}>刷新</button>
        </div>
        {err && <ErrorState message={err} onRetry={reload} />}
        {!err && tasks === null && <Loading />}
        {!err && tasks?.length === 0 && (
          <EmptyState title="暂无识别任务"
            next="去“即时识别”上传一张货架照片" />
        )}
        {tasks && tasks.length > 0 && (
          <table className="table">
            <thead><tr><th>入口</th><th>状态</th><th>输入</th><th>检出</th>
              <th>Profile</th><th>来源</th><th>发起人</th><th>时间</th>
            </tr></thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.task_id} className="row-clickable"
                  tabIndex={0} role="button"
                  aria-label={`查看任务 ${t.task_id.slice(0, 8)} 详情`}
                  onClick={() => openDetail(t.task_id)}
                  onKeyDown={(e) => e.key === "Enter"
                    && openDetail(t.task_id)}>
                  <td data-label="入口">{ENTRY_CN[t.entry] ?? t.entry}</td>
                  <td data-label="状态"><span className={t.status === "completed"
                    ? "pill-healthy" : "pill-unavailable"}>
                    {STATUS_CN[t.status] ?? t.status}</span></td>
                  <td data-label="输入">{t.file_count}</td>
                  <td data-label="检出">{t.sku_count}</td>
                  <td data-label="Profile" className="v">
                    {t.recognition_profile_id || "—"}</td>
                  <td data-label="来源" className="v">{t.source || "—"}</td>
                  <td data-label="发起人">{t.created_by}</td>
                  <td data-label="时间" className="v">{t.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {detailErr && <ErrorState message={`详情加载失败：${detailErr}`}
          onRetry={() => detail && openDetail(detail.task.task_id)} />}
        {detail && (
          <DetailDrawer
            title={`识别任务 · ${detail.task.task_id.slice(0, 8)}…`}
            onClose={() => setDetail(null)}>
            <section>
              <h4>契约（冻结）</h4>
              <div className="detail-kv">
                <b>Profile</b><span>{detail.contract.recognition_profile_id}</span>
                <b>服务档位</b><span>{detail.contract.service_tier}</span>
                <b>来源</b><span>{detail.contract.source}</span>
                <b>trace_id</b><span>{detail.contract.trace_id}</span>
                <b>项目</b><span>{detail.contract.project_id || "—"}</span>
              </div>
            </section>
            <section>
              <h4>输入 / 输出</h4>
              <div className="detail-kv">
                <b>入口</b><span>{ENTRY_CN[detail.inputs.entry]
                  ?? detail.inputs.entry}</span>
                <b>文件数</b><span>{detail.inputs.file_count}</span>
                <b>检出总数</b><span>{detail.outputs.sku_count}</span>
                <b>状态</b><span>{STATUS_CN[detail.outputs.status]
                  ?? detail.outputs.status}</span>
              </div>
              {detail.outputs.results.slice(0, 3).map((r: any, i) => {
                // 真实结构：products 为逐检出项（无 count 字段），
                // 按名称聚合计数，不得渲染 undefined
                const prods: any[] = r.products ?? [];
                const byName: Record<string, number> = {};
                prods.forEach((p: any) => {
                  const k = p.name ?? p.sku_id ?? "未知";
                  byName[k] = (byName[k] ?? 0) + (p.count ?? 1);
                });
                return (
                  <p key={i} className="v" style={{ fontSize: 12 }}>
                    {r.name}：{r.count ?? prods.length} 件
                    {Object.entries(byName).slice(0, 3)
                      .map(([n, c]) => ` ${n}×${c}`).join("、")}
                  </p>
                );
              })}
            </section>
            {detail.errors.length > 0 && (
              <section>
                <h4>错误</h4>
                {detail.errors.map((e) => <p key={e} className="v"
                  style={{ color: "var(--err, #c92f2f)" }}>⚠ {e}</p>)}
              </section>
            )}
            <section>
              <h4>时间线</h4>
              {detail.timeline.map((ev, i) => (
                <p key={i} className="v" style={{ fontSize: 12 }}>
                  {ev.event} · {ev.detail}</p>
              ))}
            </section>
            <section>
              <h4>证据 / 用量 / 关联</h4>
              {detail.evidence.refs.length > 0
                ? detail.evidence.refs.map((ref) => (
                  <p key={ref} className="v" style={{ fontSize: 12 }}>
                    证据：{ref}</p>))
                : <p className="v" style={{ fontSize: 12 }}>
                    {detail.evidence.note}</p>}
              {detail.usage.events.length > 0
                ? detail.usage.events.map((u: any, i) => (
                  <p key={i} className="v" style={{ fontSize: 12 }}>
                    用量：{u.unit} × {u.quantity}
                    {u.profile_id ? ` · profile ${u.profile_id}` : ""}
                    {u.tier ? ` · tier ${u.tier}` : ""}</p>))
                : <p className="v" style={{ fontSize: 12 }}>
                    {detail.usage.note}</p>}
              <p className="v" style={{ fontSize: 12 }}>
                work/run：{detail.relations.run_id
                  ? `run ${detail.relations.run_id} · work ${detail.relations.work_id}`
                  : detail.relations.note}</p>
            </section>
            <section>
              <h4>下一动作</h4>
              {detail.next_actions.map((a) => <p key={a} className="v"
                style={{ fontSize: 12 }}>· {a}</p>)}
            </section>
          </DetailDrawer>
        )}
      </div>
    </>
  );
}

// ---- /vision/annotation ----
export function VisionAnnotation({ health }:
  { health: HealthBody | null }) {
  return (
    <>
      <PageHeader title="标注与审核"
        desc="Label Studio 项目、审核队列与人工金标准" />
      <LabelStudioHub />
      <Annotation health={health} />
    </>
  );
}

// ---- /vision/datasets ----
export function VisionDatasets() {
  return (
    <>
      <PageHeader title="数据集与资产"
        desc="真实资产台账、快照与质量门禁" />
      <Assets />
    </>
  );
}

// ---- /vision/models ----
export function VisionModels() {
  return (
    <>
      <PageHeader title="模型与训练"
        desc="候选模型、驻留与训练治理（本轮不训练）" />
      <Training />
      <ModelRuntime />
    </>
  );
}

// ---- /vision/evidence ----
export function VisionEvidence() {
  const [gold, setGold] = useState<any | null>(null);
  const [review, setReview] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([fetchGoldStatus().catch(() => null),
      fetchReviewStatus().catch(() => null)])
      .then(([g, r]) => {
        if (!g && !r) setErr("质量与证据服务暂不可用");
        setGold(g); setReview(r);
      });
  }, []);
  return (
    <>
      <PageHeader title="质量与证据"
        desc="质量判定、人工金标准与审核链（真实计数，不硬编码）" />
      {err && <ErrorState message={err} />}
      {!gold && !review && !err && <Loading />}
      <div className="grid">
        {gold && (
          <div className="card">
            <h3>人工金标准</h3>
            <p className="k">gold_verified：
              {gold.counts?.gold_verified ?? gold.gold_verified ?? 0}</p>
            <p className="v">状态计数来自 quality_gold_v1 实时查询。</p>
            <pre style={{ fontSize: 11 }}>{JSON.stringify(gold, null, 1)
              .slice(0, 500)}</pre>
          </div>
        )}
        {review && (
          <div className="card">
            <h3>审核队列</h3>
            <pre style={{ fontSize: 11 }}>{JSON.stringify(review, null, 1)
              .slice(0, 500)}</pre>
          </div>
        )}
      </div>
    </>
  );
}
