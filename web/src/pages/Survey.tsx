// ABOSV2 Phase E：调研与问卷（设计 / 分配与填写 / 报表输入）。
// 全部来自真实 API；suggestion 必须人工终审；修正走 correction 通道。
import { useEffect, useState } from "react";
import { csrfToken, iamGet, iamPost } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader }
  from "../platform/components";

async function putJson(path: string, body: unknown): Promise<any> {
  const csrfH: Record<string, string> = csrfToken()
    ? { "X-CSRF-Token": csrfToken() as string } : {};
  const r = await fetch(`/api/v1/${path.replace(/^\/+/, "")}`, {
    method: "PUT",
    headers: { "content-type": "application/json", ...csrfH },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

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

// ---- 1. 问卷设计 ----
export function SurveyDesign() {
  const defs = useLoad<any>("survey/definitions");
  const [msg, setMsg] = useState<string | null>(null);
  const act = async (name: string, fn: () => Promise<any>) => {
    setMsg(null);
    try { const out = await fn(); setMsg(`${name}成功`); defs.reload();
      return out; }
    catch (e) { setMsg(`${name}失败：${e instanceof Error ? e.message : e}`); }
  };
  return (
    <>
      <PageHeader title="问卷设计"
        desc="题型/跳题 DAG/评分规则/版本；发布后不可原地修改" />
      <div className="card">
        <h3>从样板模板创建草稿（含全部首批题型）</h3>
        <button className="btn small primary"
          onClick={() => act("创建", () => iamPost("survey/definitions",
            { template_id: "tpl_store_visit_v1" }))}>
          实例化门店巡检样板</button>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {defs.err && <ErrorState message={defs.err} onRetry={defs.reload} />}
      {!defs.data && !defs.err && <Loading />}
      {defs.data && (defs.data.definitions.length === 0
        ? <EmptyState title="暂无问卷定义" />
        : defs.data.definitions.map((d: any) => (
          <div className="card" key={`${d.survey_id}@${d.version}`}>
            <h3>{d.name} <span className="v">{d.survey_id} ·
              v{d.version} · {d.status}</span></h3>
            <p className="v" style={{ fontSize: 12 }}>
              题目：{(d.spec?.questions ?? []).map(
                (q: any) => `${q.id}(${q.type})`).join("、")}
              · 跳题边 {(d.spec?.logic_edges ?? []).length} 条</p>
            {(d.lint_report ?? []).length > 0 && (
              <ul style={{ fontSize: 12 }}>
                {d.lint_report.map((i: any, k: number) => (
                  <li key={k} style={{ color: i.level === "error"
                    ? "var(--err)" : "inherit" }}>
                    [{i.level}] {i.code}: {i.message}</li>
                ))}
              </ul>
            )}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button className="btn small"
                onClick={() => act("lint", () => iamPost(
                  `survey/definitions/${d.survey_id}/lint`, {}))}>lint</button>
              <button className="btn small primary"
                onClick={() => act("发布", () => iamPost(
                  `survey/definitions/${d.survey_id}/publish`, {}))}>
                发布</button>
              <button className="btn small"
                onClick={() => act("新版本", () => iamPost(
                  `survey/definitions/${d.survey_id}/new-version`, {}))}>
                新版本</button>
            </div>
          </div>
        )))}
    </>
  );
}

// ---- 2. 分配与填写 ----
export function SurveyField() {
  const defs = useLoad<any>("survey/definitions");
  const asgs = useLoad<any>("survey/assignments");
  const [sel, setSel] = useState<any | null>(null);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState<string | null>(null);

  const openResponse = async (assignmentId: string) => {
    setMsg(null);
    try {
      const out = await iamPost("survey/responses",
        { assignment_id: assignmentId });
      setSel(out.response); setAnswers({});
    } catch (e) { setMsg(`开始填写失败：${e instanceof Error
      ? e.message : e}`); }
  };
  const setAnswer = (qid: string, value: any) =>
    setAnswers((a) => ({ ...a, [qid]: { value } }));

  const spec = (defs.data?.definitions ?? []).find(
    (d: any) => sel && d.survey_id === sel.survey_id
      && d.version === sel.survey_version)?.spec;

  return (
    <>
      <PageHeader title="分配与填写"
        desc="分配→作答→拍照证据→识别建议人工终审→提交评分" />
      <div className="card">
        <h3>新建分配</h3>
        <AssignForm defs={defs.data?.definitions ?? []}
          onDone={() => asgs.reload()} setMsg={setMsg} />
      </div>
      {asgs.err && <ErrorState message={asgs.err} onRetry={asgs.reload} />}
      {asgs.data && (asgs.data.assignments.length === 0
        ? <EmptyState title="暂无分配" next="先发布问卷再分配" />
        : (
          <table className="table">
            <thead><tr><th>assignment</th><th>问卷</th><th>客户</th>
              <th>状态</th><th /></tr></thead>
            <tbody>
              {asgs.data.assignments.map((a: any) => (
                <tr key={a.assignment_id}>
                  <td data-label="assignment" className="v">
                    {a.assignment_id}</td>
                  <td data-label="问卷">{a.survey_id}
                    @v{a.survey_version}</td>
                  <td data-label="客户">{a.customer_id}</td>
                  <td data-label="状态">{a.status}</td>
                  <td><button className="btn small"
                    onClick={() => openResponse(a.assignment_id)}>
                    开始填写</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      {sel && spec && (
        <div className="card">
          <h3>填写：{sel.response_id}（{sel.status}）</h3>
          {(spec.questions ?? []).map((q: any) => (
            <div key={q.id} style={{ marginBottom: 10 }}>
              <b style={{ fontSize: 13 }}>{q.id} · {q.title}
                （{q.type}）{q.required ? " *" : ""}</b>
              {q.type === "single_choice" && (
                <select aria-label={q.id} style={{ marginLeft: 8 }}
                  onChange={(e) => setAnswer(q.id, e.target.value)}>
                  <option value="">选择…</option>
                  {(q.options ?? []).map((o: any) => (
                    <option key={o.value} value={o.value}>
                      {o.label ?? o.value}</option>
                  ))}
                </select>
              )}
              {(q.type === "multi_choice") && (
                <div style={{ fontSize: 12 }}>
                  {(q.options ?? []).map((o: any) => (
                    <label key={o.value} style={{ marginRight: 8 }}>
                      <input type="checkbox"
                        onChange={(e) => {
                          const cur: string[] =
                            answers[q.id]?.value ?? [];
                          setAnswer(q.id, e.target.checked
                            ? [...cur, o.value]
                            : cur.filter((v) => v !== o.value));
                        }} />
                      {o.label ?? o.value}
                      {o.sku_ref ? "（SKU 库引用）" : ""}
                    </label>
                  ))}
                </div>
              )}
              {(q.type === "text") && (
                <input style={{ marginLeft: 8 }} aria-label={q.id}
                  placeholder={q.input_type ?? "text"}
                  onChange={(e) => setAnswer(q.id,
                    q.input_type === "number"
                      ? Number(e.target.value) : e.target.value)} />
              )}
              {q.type === "rating" && (
                <select aria-label={q.id} style={{ marginLeft: 8 }}
                  onChange={(e) => setAnswer(q.id,
                    Number(e.target.value))}>
                  <option value="">评分…</option>
                  {Array.from({ length: (q.max ?? 5) - (q.min ?? 1) + 1 },
                    (_, i) => (q.min ?? 1) + i).map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              )}
              {q.type === "photo" && (
                <PhotoPanel responseId={sel.response_id} q={q}
                  onMsg={setMsg} />
              )}
            </div>
          ))}
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <button className="btn small" onClick={async () => {
              try {
                await putJson(`survey/responses/${sel.response_id
                  }/answers`, { answers });
                setMsg("草稿已保存");
              } catch (e) { setMsg(`保存失败：${e}`); }
            }}>保存草稿</button>
            <button className="btn small primary" onClick={async () => {
              try {
                await putJson(`survey/responses/${sel.response_id
                  }/answers`, { answers });
                const out = await iamPost(
                  `survey/responses/${sel.response_id}/submit`, {});
                setSel(out.response);
                setMsg(`已提交：总分 ${out.response.scores?.total}（评分版本
                  ${out.response.score_version}）`);
              } catch (e) { setMsg(`提交失败：${e instanceof Error
                ? e.message : e}`); }
            }}>提交（自动评分）</button>
          </div>
        </div>
      )}
      {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
    </>
  );
}

function AssignForm({ defs, onDone, setMsg }: {
  defs: any[]; onDone: () => void; setMsg: (m: string) => void;
}) {
  const [form, setForm] = useState({ survey_id: "", customer_id: "",
    project_id: "", assignee: "" });
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <select value={form.survey_id} aria-label="问卷"
        onChange={(e) => setForm({ ...form, survey_id: e.target.value })}>
        <option value="">选择已发布问卷…</option>
        {defs.filter((d) => d.status === "published").map((d) => (
          <option key={`${d.survey_id}@${d.version}`}
            value={d.survey_id}>{d.name}（{d.survey_id}）</option>
        ))}
      </select>
      <input placeholder="customer_id" aria-label="客户"
        value={form.customer_id}
        onChange={(e) => setForm({ ...form,
          customer_id: e.target.value })} />
      <input placeholder="assignee" aria-label="执行人"
        value={form.assignee}
        onChange={(e) => setForm({ ...form, assignee: e.target.value })} />
      <button className="btn small primary" onClick={async () => {
        try {
          await iamPost("survey/assignments", form);
          setMsg("分配成功"); onDone();
        } catch (e) { setMsg(`分配失败：${e instanceof Error
          ? e.message : e}`); }
      }}>分配</button>
    </div>
  );
}

function PhotoPanel({ responseId, q, onMsg }: {
  responseId: string; q: any; onMsg: (m: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [metas, setMetas] = useState({ lat: "31.23", lng: "121.47",
    device: "web-browser" });
  const [medias, setMedias] = useState<any[]>([]);
  const [role, setRole] = useState<string>(q.capture_role ?? "other");
  const toB64 = (f: File) => new Promise<string>((res, rej) => {
    const rd = new FileReader();
    rd.onload = () => res(String(rd.result).split(",")[1]);
    rd.onerror = rej; rd.readAsDataURL(f);
  });
  return (
    <div style={{ border: "1px dashed var(--border)", padding: 8,
      marginTop: 4 }}>
      {q.require_storefront && (
        <p className="v" style={{ fontSize: 12, color: "var(--warn)" }}>
          门头必拍：必须上传至少 1 张 capture_role=storefront 的照片；
          缺门头照无法提交。</p>)}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input type="file" accept="image/*" aria-label={`${q.id} 照片`}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <select aria-label="拍摄角色" value={role}
          onChange={(e) => setRole(e.target.value)}>
          <option value="storefront">storefront 门头</option>
          <option value="shelf">shelf 货架</option>
          <option value="employee_selfie">employee_selfie 自拍</option>
          <option value="product">product 商品</option>
          <option value="other">other 其他</option>
        </select>
        <input style={{ width: 90 }} aria-label="纬度" value={metas.lat}
          onChange={(e) => setMetas({ ...metas, lat: e.target.value })} />
        <input style={{ width: 90 }} aria-label="经度" value={metas.lng}
          onChange={(e) => setMetas({ ...metas, lng: e.target.value })} />
        <input style={{ width: 140 }} aria-label="设备"
          value={metas.device}
          onChange={(e) => setMetas({ ...metas, device: e.target.value })} />
        <button className="btn small" disabled={!file}
          onClick={async () => {
            if (!file) return;
            try {
              const out = await iamPost(
                `survey/responses/${responseId}/media`, {
                  question_id: q.id,
                  location: { lat: Number(metas.lat),
                    lng: Number(metas.lng) },
                  taken_at: new Date().toISOString(),
                  device: metas.device,
                  quality: { width: 0, note: "web 上传无质量探测" },
                  image_b64: await toB64(file),
                  capture_role: role,
                });
              setMedias((m) => [...m, out.media]);
              onMsg(`照片已入库（${out.media.capture_role}）：识别建议 `
                + `${out.media.suggestion_status}（需人工终审）`);
            } catch (e) { onMsg(`照片上传失败：${e instanceof Error
              ? e.message : e}`); }
          }}>上传（位置/时间/设备证据）</button>
      </div>
      {medias.map((m) => (
        <div key={m.media_id} className="v" style={{ fontSize: 12,
          marginTop: 6 }}>
          {m.media_id} · 角色 {m.capture_role ?? "other"} · 状态
          {" "}{m.status ?? "active"} · 建议状态 {m.suggestion_status}
          {m.suggestion_status === "accepted" && (
            <span style={{ color: "var(--ok)" }}> · 人工已接受
              （final）</span>)}
          {m.suggestion_status === "rejected" && (
            <span style={{ color: "var(--err)" }}> · 人工已拒绝
              （反馈进评估链）</span>)}
          {m.suggestion?.task_id ? ` · 识别任务 ${m.suggestion.task_id}`
            : ""}
          {m.suggestion_status === "pending" && (
            <span style={{ marginLeft: 8 }}>
              <button className="btn small" onClick={async () => {
                try {
                  const out = await iamPost(
                    `survey/media/${m.media_id}/review`,
                    { decision: "accepted" });
                  setMedias((ms) => ms.map((x) => x.media_id === m.media_id
                    ? out.media : x));
                  onMsg("已接受建议（final answer 生效）");
                } catch (e) { onMsg(`终审失败：${e}`); }
              }}>接受建议</button>
              <button className="btn small danger"
                style={{ marginLeft: 4 }} onClick={async () => {
                  try {
                    const out = await iamPost(
                      `survey/media/${m.media_id}/review`,
                      { decision: "rejected" });
                    setMedias((ms) => ms.map((x) => x.media_id === m.media_id
                      ? out.media : x));
                    onMsg("已拒绝建议（反馈进评估链，training_truth=false）");
                  } catch (e) { onMsg(`终审失败：${e}`); }
                }}>拒绝</button>
            </span>
          )}
        </div>
      ))}
      <p className="v" style={{ fontSize: 11, marginTop: 4 }}>
        识别结果只是 suggestion：接受/拒绝/修改后才成为 final answer；
        反馈进入报表与模型评估链，但不会自动成为训练真值。</p>
    </div>
  );
}

// ---- 3. 报表输入 ----
export function SurveyReport() {
  const defs = useLoad<any>("survey/definitions");
  const [sid, setSid] = useState("");
  const [rep, setRep] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="报表输入"
        desc="final 答案 + 评分版本聚合；BI 只读消费本端点" />
      <div className="card">
        <select value={sid} aria-label="选择问卷"
          onChange={(e) => setSid(e.target.value)}>
          <option value="">选择问卷…</option>
          {(defs.data?.definitions ?? []).map((d: any) => (
            <option key={d.survey_id} value={d.survey_id}>
              {d.name}（{d.survey_id}）</option>
          ))}
        </select>
        <button className="btn small" style={{ marginLeft: 8 }}
          disabled={!sid} onClick={async () => {
            setErr(null);
            try {
              setRep(await iamGet(`survey/report?survey_id=${sid}`));
            } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
          }}>生成报表输入</button>
        {err && <p className="v" style={{ color: "var(--err)" }}>{err}</p>}
        {rep && (
          <div style={{ marginTop: 8 }}>
            <p className="v">响应 {rep.responses} · 已提交 {rep.submitted}
              · 总分 {rep.total_score} · 均分 {rep.avg_score ?? "—"} ·
              评分版本最高 {rep.score_version_max}</p>
            {(rep.items ?? []).map((it: any) => (
              <p key={it.response_id} className="v" style={{ fontSize: 12 }}>
                {it.response_id} · {it.respondent} · {it.status} ·
                总分 {it.scores?.total ?? "—"}（v{it.scores
                  ?.scoring_version ?? "—"}）</p>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
