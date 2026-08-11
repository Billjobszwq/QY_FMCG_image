// ABOSV3 T6：从空白自定义问卷 Builder。
// 题型库（含 SKU/客户/项目绑定）+ 画布（排序/复制/删除）+ 属性面板
// （选项/必填/校验/分值/维度/照片配置）+ 跳题编辑 + lint + 预览
// （桌面/移动；测试答案不入库）+ 发布/新版本。
import { useCallback, useEffect, useState } from "react";
import { EmptyState, ErrorState, PageHeader } from
  "../platform/components";

// 复用问卷 API（与 Survey.tsx 相同的端点）
async function api(path: string, opts?: RequestInit) {
  const r = await fetch(`/api/v1${path}`, opts);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(`${d.detail ?? path}（HTTP ${r.status}）`);
  }
  return r.json();
}
async function post(path: string, body: unknown = {},
  method = "POST") {
  const headers: Record<string, string> =
    { "content-type": "application/json" };
  try {
    const mod = await import("../api");
    const t = (mod as any).csrfToken?.();
    if (t) headers["X-CSRF-Token"] = t;
  } catch { /* noop */ }
  return api(path, { method, headers, body: JSON.stringify(body) });
}

const QTYPES: { type: string; label: string }[] = [
  { type: "single_choice", label: "单选题" },
  { type: "multi_choice", label: "多选题" },
  { type: "text", label: "填空（文本/数字/日期）" },
  { type: "rating", label: "打分题" },
  { type: "matrix", label: "矩阵题" },
  { type: "photo", label: "拍照题" },
  { type: "description", label: "说明文字" },
];
const BIND_SOURCES = ["", "sku_library", "customer_library",
  "project_library"];

let qSeq = 0;
function newQuestion(type: string): any {
  qSeq += 1;
  const id = `q${Date.now().toString(36)}${qSeq}`;
  const base: any = { id, type, title: `新${type}题`, required: false };
  if (type === "single_choice" || type === "multi_choice") {
    base.options = [{ value: "opt1", label: "选项1" },
      { value: "opt2", label: "选项2" }];
  }
  if (type === "matrix") {
    base.rows = [{ id: "r1", label: "行1" }];
    base.options = [{ value: "good", label: "好" },
      { value: "bad", label: "差" }];
  }
  if (type === "text") base.input_type = "text";
  if (type === "rating") { base.min = 1; base.max = 5; }
  if (type === "photo") {
    base.min_count = 1; base.require_storefront = true;
    base.selfie_optional = false; base.recognition = true;
    base.quality = { min_width: 320 };
  }
  return base;
}

export default function SurveyBuilder() {
  const [surveys, setSurveys] = useState<any[]>([]);
  const [selId, setSelId] = useState("");
  const [survey, setSurvey] = useState<any | null>(null);
  const [spec, setSpec] = useState<any>({ questions: [],
    logic_edges: [], scoring: { version: 1, rules: [], formula: "sum" },
    sections: [] });
  const [selQ, setSelQ] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lint, setLint] = useState<any[] | null>(null);
  const [preview, setPreview] = useState<"off" | "desktop" | "mobile">(
    "off");
  const [testAnswers, setTestAnswers] = useState<Record<string, any>>({});
  const [libOptions, setLibOptions] = useState<Record<string, any[]>>({});

  const loadList = useCallback(() => {
    api("/survey/definitions").then((d) => {
      const latest = new Map<string, any>();
      for (const s of d.surveys ?? d.definitions ?? []) {
        const k = s.survey_id;
        if (!latest.has(k) || latest.get(k).version < s.version) {
          latest.set(k, s);
        }
      }
      setSurveys([...latest.values()]);
    }).catch((e) => setErr(String(e.message ?? e)));
  }, []);
  useEffect(() => { loadList(); }, [loadList]);

  useEffect(() => {
    if (!selId) return;
    api(`/survey/definitions/${selId}`).then((d) => {
      setSurvey(d.definition ?? d.survey);
      setSpec((d.definition ?? d.survey).spec ?? { questions: [] });
      setLint((d.definition ?? d.survey).lint_report ?? null);
    }).catch((e) => setErr(String(e.message ?? e)));
  }, [selId]);

  useEffect(() => {
    // 绑定库题目：预览时加载 SKU/客户/项目选项
    api("/master/skus").then((d) => setLibOptions((o) => ({ ...o,
      sku_library: (d.skus ?? []).map((s: any) => ({
        value: s.sku_id, label: s.canonical_name })) }))).catch(() => { });
    api("/master/customers").then((d) => setLibOptions((o) => ({ ...o,
      customer_library: (d.customers ?? []).map((s: any) => ({
        value: s.customer_id, label: s.name })) }))).catch(() => { });
    api("/master/customers").then((d) => setLibOptions((o) => ({ ...o,
      project_library: (d.customers ?? []).map((s: any) => ({
        value: s.customer_id, label: `项目·${s.name}` })) })))
      .catch(() => { });
  }, []);

  const createBlank = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await post("/survey/definitions", {
        name: `空白问卷 ${new Date().toLocaleString()}`,
        spec: { questions: [], logic_edges: [],
          scoring: { version: 1, rules: [], formula: "sum" } },
      });
      setMsg(`已创建 ${d.definition.survey_id}`);
      loadList(); setSelId(d.definition.survey_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const save = async () => {
    if (!survey) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const d = await post(`/survey/definitions/${survey.survey_id}`,
        { spec }, "PUT");
      setSurvey(d.definition); setMsg("已保存 draft");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const doLint = async () => {
    if (!survey) return;
    setBusy(true); setErr(null);
    try {
      await save();
      const d = await post(`/survey/definitions/${survey.survey_id}/lint`);
      setLint(d.definition.lint_report ?? []);
      setSurvey(d.definition);
      setMsg("lint 完成");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const publish = async () => {
    if (!survey) return;
    setBusy(true); setErr(null);
    try {
      const d = await post(
        `/survey/definitions/${survey.survey_id}/publish`);
      setSurvey(d.definition);
      setMsg(`已发布 v${d.definition.version}（发布后不可原地修改）`);
      loadList();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const newVersion = async () => {
    if (!survey) return;
    setBusy(true); setErr(null);
    try {
      const d = await post(
        `/survey/definitions/${survey.survey_id}/new-version`);
      setMsg(`已创建新版本草稿 v${d.definition.version}`);
      loadList(); setSelId(survey.survey_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const addQuestion = (type: string) => {
    const q = newQuestion(type);
    setSpec({ ...spec, questions: [...(spec.questions ?? []), q] });
    setSelQ(q.id);
  };
  const updateQ = (id: string, patch: any) => {
    setSpec({ ...spec, questions: spec.questions.map((q: any) =>
      q.id === id ? { ...q, ...patch } : q) });
  };
  const removeQ = (id: string) => {
    setSpec({ ...spec,
      questions: spec.questions.filter((q: any) => q.id !== id),
      logic_edges: (spec.logic_edges ?? []).filter(
        (e: any) => e.from !== id) });
    if (selQ === id) setSelQ(null);
  };
  const duplicateQ = (id: string) => {
    const q = spec.questions.find((x: any) => x.id === id);
    if (!q) return;
    qSeq += 1;
    const copy = JSON.parse(JSON.stringify(q));
    copy.id = `${q.id}c${qSeq}`;
    const idx = spec.questions.findIndex((x: any) => x.id === id);
    const qs = [...spec.questions];
    qs.splice(idx + 1, 0, copy);
    setSpec({ ...spec, questions: qs });
  };
  const moveQ = (id: string, dir: -1 | 1) => {
    const idx = spec.questions.findIndex((x: any) => x.id === id);
    const ni = idx + dir;
    if (idx < 0 || ni < 0 || ni >= spec.questions.length) return;
    const qs = [...spec.questions];
    const [q] = qs.splice(idx, 1);
    qs.splice(ni, 0, q);
    setSpec({ ...spec, questions: qs });
  };

  const selQuestion = spec.questions?.find((q: any) => q.id === selQ);

  return (
    <>
      <PageHeader title="问卷设计器（从空白搭建）"
        desc="题型库 → 画布（排序/复制/删除）→ 属性面板（选项/必填/分值/照片）→ 跳题 → lint → 预览 → 发布；样板仅作模板" />
      {err && <ErrorState message={err}
        onRetry={() => setErr(null)} />}
      {msg && <div className="banner banner-info">{msg}</div>}

      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "center" }}>
          <button className="btn primary" onClick={createBlank}
            disabled={busy}>从空白新建</button>
          <select value={selId} aria-label="选择问卷"
            onChange={(e) => setSelId(e.target.value)}>
            <option value="">选择问卷…</option>
            {surveys.map((s) => (
              <option key={s.survey_id} value={s.survey_id}>
                {s.name}（v{s.version} · {s.status}）</option>))}
          </select>
          <button className="btn" onClick={save} disabled={busy || !survey}
          >保存 draft</button>
          <button className="btn" onClick={doLint}
            disabled={busy || !survey}>lint</button>
          <button className="btn primary" onClick={publish}
            disabled={busy || !survey}>发布</button>
          <button className="btn" onClick={newVersion}
            disabled={busy || !survey}>新版本</button>
          <span style={{ flex: 1 }} />
          <button className="btn small" onClick={() => setPreview(
            preview === "off" ? "desktop" : "off")}>
            {preview === "off" ? "预览" : "退出预览"}</button>
          {preview !== "off" && (
            <button className="btn small" onClick={() => setPreview(
              preview === "desktop" ? "mobile" : "desktop")}>
              {preview === "desktop" ? "移动端" : "桌面端"}</button>)}
        </div>
        {survey && <p className="v" style={{ marginTop: 6 }}>
          {survey.name} · v{survey.version} · 状态 {survey.status}
          {" "}· 题目 {spec.questions?.length ?? 0}
          {survey.status === "published" &&
            " · 已发布不可原地修改（编辑请新版本）"}</p>}
        {lint && (
          <div style={{ marginTop: 6 }}>
            {lint.length === 0
              ? <p className="v" style={{ color: "var(--ok)" }}>
                lint 通过（无问题）</p>
              : lint.map((i: any, k: number) => (
                <p key={k} className="v" style={{ color:
                  i.level === "error" ? "var(--err)" : "var(--warn)" }}>
                  [{i.level}] {i.code}: {i.message}</p>))}
          </div>)}
      </div>

      {preview !== "off" && survey ? (
        <div className="card">
          <h3>预览（{preview === "mobile" ? "移动端 375px"
            : "桌面端"}）· 测试答案不入库</h3>
          <div style={{ maxWidth: preview === "mobile" ? 375 : "100%",
            margin: "0 auto", border: preview === "mobile"
              ? "2px dashed var(--border-strong)" : "none",
            borderRadius: 12, padding: preview === "mobile" ? 10 : 0 }}>
            {(spec.questions ?? []).map((q: any) => (
              <div key={q.id} className="card"
                style={{ marginBottom: 8 }}>
                <h3 style={{ fontSize: 13 }}>{q.title}
                  {q.required && <span style={{ color: "var(--err)" }}>
                    {" "}*</span>}</h3>
                {q.type === "description" && (
                  <p className="v">{q.text ?? ""}</p>)}
                {(q.type === "single_choice") && (
                  <div>
                    {(q.source && libOptions[q.source]
                      ? libOptions[q.source] : q.options ?? []).map(
                      (o: any) => (
                        <label key={o.value} className="v">
                          <input type="radio" name={q.id}
                            checked={testAnswers[q.id]?.value === o.value}
                            onChange={() => setTestAnswers((a) => ({
                              ...a, [q.id]: { value: o.value } }))} />
                          {" "}{o.label}</label>))}
                  </div>)}
                {q.type === "multi_choice" && (
                  <div>
                    {(q.options ?? []).map((o: any) => (
                      <label key={o.value} className="v">
                        <input type="checkbox"
                          checked={((testAnswers[q.id]?.value) ?? [])
                            .includes(o.value)}
                          onChange={(e) => {
                            const cur = testAnswers[q.id]?.value ?? [];
                            setTestAnswers((a) => ({ ...a, [q.id]: {
                              value: e.target.checked
                                ? [...cur, o.value]
                                : cur.filter((x: string) =>
                                  x !== o.value) } }));
                          }} /> {o.label}</label>))}
                  </div>)}
                {q.type === "text" && (
                  <input style={{ width: "100%" }}
                    type={q.input_type === "number" ? "number"
                      : q.input_type === "date" ? "date" : "text"}
                    value={testAnswers[q.id]?.value ?? ""}
                    onChange={(e) => setTestAnswers((a) => ({ ...a,
                      [q.id]: { value: e.target.value } }))} />)}
                {q.type === "rating" && (
                  <input type="range" min={q.min ?? 1} max={q.max ?? 5}
                    value={testAnswers[q.id]?.value ?? q.min ?? 1}
                    onChange={(e) => setTestAnswers((a) => ({ ...a,
                      [q.id]: { value: Number(e.target.value) } }))} />)}
                {q.type === "matrix" && (
                  <table className="table">
                    <tbody>
                      {(q.rows ?? []).map((r: any) => (
                        <tr key={r.id}>
                          <td>{r.label}</td>
                          <td>
                            {(q.options ?? []).map((o: any) => (
                              <label key={o.value} className="v"
                                style={{ marginRight: 8 }}>
                                <input type="radio"
                                  name={`${q.id}-${r.id}`}
                                  checked={testAnswers[q.id]?.value?.[
                                    r.id] === o.value}
                                  onChange={() => setTestAnswers((a) => ({
                                    ...a, [q.id]: { value: {
                                      ...(a[q.id]?.value ?? {}),
                                      [r.id]: o.value } } }))} />
                                {o.label}</label>))}
                          </td>
                        </tr>))}
                    </tbody>
                  </table>)}
                {q.type === "photo" && (
                  <p className="v">📷 最少 {q.min_count ?? 0} 张
                    {q.require_storefront ? " · 门头必拍" : ""}
                    {q.selfie_optional ? " · 自拍可选" : ""}
                    {q.recognition ? " · 识别建议需人工确认" : ""}
                    （预览模式不上传）</p>)}
              </div>))}
          </div>
        </div>
      ) : survey && (
        <div style={{ display: "grid",
          gridTemplateColumns: "220px 1fr 300px", gap: 12 }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>题型库</h3>
            {QTYPES.map((t) => (
              <button key={t.type} className="btn"
                style={{ display: "block", width: "100%",
                  marginBottom: 6 }}
                disabled={survey.status !== "draft"}
                onClick={() => addQuestion(t.type)}>+ {t.label}</button>))}
            <p className="v" style={{ fontSize: 11 }}>
              SKU/客户/项目绑定：添加单选题后在属性面板选择"数据绑定"。
            </p>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>画布（{spec.questions?.length ?? 0} 题）</h3>
            {(spec.questions ?? []).length === 0
              ? <EmptyState title="从左侧题型库添加题目" />
              : spec.questions.map((q: any, i: number) => (
                <div key={q.id} className="note-card"
                  onClick={() => setSelQ(q.id)}
                  style={{ cursor: "pointer", borderLeft: selQ === q.id
                    ? "4px solid var(--info)" : undefined }}>
                  <div style={{ display: "flex",
                    justifyContent: "space-between" }}>
                    <b>{i + 1}. {q.title}</b>
                    <span className="meta">{q.type}
                      {q.required ? " · 必填" : ""}
                      {q.source ? ` · 绑定${q.source}` : ""}</span>
                  </div>
                  <div style={{ marginTop: 4, display: "flex", gap: 4 }}>
                    <button className="btn small" onClick={(e) => {
                      e.stopPropagation(); moveQ(q.id, -1); }}>↑</button>
                    <button className="btn small" onClick={(e) => {
                      e.stopPropagation(); moveQ(q.id, 1); }}>↓</button>
                    <button className="btn small" onClick={(e) => {
                      e.stopPropagation(); duplicateQ(q.id);
                    }}>复制</button>
                    <button className="btn small danger" onClick={(e) => {
                      e.stopPropagation(); removeQ(q.id);
                    }}>删除</button>
                  </div>
                </div>))}
            <h3 style={{ marginTop: 10 }}>跳题逻辑（DAG）</h3>
            {(spec.logic_edges ?? []).map((e: any, i: number) => (
              <div key={i} className="v" style={{ display: "flex",
                gap: 6, alignItems: "center", marginBottom: 4 }}>
                <span>{e.from} 当 {e.when?.op} {String(e.when?.value)}
                  {" "}→ {e.to}</span>
                <button className="btn small danger" onClick={() =>
                  setSpec({ ...spec, logic_edges:
                    spec.logic_edges.filter((_: any, j: number) =>
                      j !== i) })}>删</button>
              </div>))}
            <button className="btn small" onClick={() => {
              const first = spec.questions?.[0];
              if (!first) return;
              setSpec({ ...spec, logic_edges: [...(spec.logic_edges ?? []),
                { from: first.id, when: { op: "eq", value: "" },
                  to: "END_SKIP" }] });
            }}>+ 跳题边（再在属性里改）</button>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>属性面板</h3>
            {!selQuestion
              ? <p className="v">点击画布中的题目进行编辑</p>
              : (
                <div>
                  <label className="v">标题</label>
                  <input style={{ width: "100%" }}
                    value={selQuestion.title}
                    onChange={(e) => updateQ(selQuestion.id,
                      { title: e.target.value })} />
                  <label className="v" style={{ marginTop: 6,
                    display: "block" }}>
                    <input type="checkbox"
                      checked={!!selQuestion.required}
                      onChange={(e) => updateQ(selQuestion.id,
                        { required: e.target.checked })} /> 必填</label>
                  {selQuestion.type === "text" && (
                    <>
                      <label className="v">输入类型</label>
                      <select style={{ width: "100%" }}
                        value={selQuestion.input_type ?? "text"}
                        onChange={(e) => updateQ(selQuestion.id,
                          { input_type: e.target.value })}>
                        <option value="text">文本</option>
                        <option value="number">数字</option>
                        <option value="date">日期</option>
                      </select>
                    </>)}
                  {(selQuestion.type === "single_choice") && (
                    <>
                      <label className="v">数据绑定</label>
                      <select style={{ width: "100%" }}
                        value={selQuestion.source ?? ""}
                        onChange={(e) => updateQ(selQuestion.id,
                          { source: e.target.value || undefined })}>
                        {BIND_SOURCES.map((s) => (
                          <option key={s} value={s}>{s || "自定义选项"}
                          </option>))}
                      </select>
                    </>)}
                  {(selQuestion.type === "single_choice"
                    || selQuestion.type === "multi_choice"
                    || selQuestion.type === "matrix")
                    && !selQuestion.source && (
                    <>
                      <label className="v">选项（value=label 每行一个）
                      </label>
                      <textarea rows={3} style={{ width: "100%" }}
                        value={(selQuestion.options ?? []).map(
                          (o: any) => `${o.value}=${o.label}`).join("\n")}
                        onChange={(e) => updateQ(selQuestion.id, {
                          options: e.target.value.split("\n")
                            .filter(Boolean).map((ln) => {
                              const [v, l] = ln.split("=");
                              return { value: v.trim(),
                                label: (l ?? v).trim() };
                            }) })} />
                    </>)}
                  {selQuestion.type === "matrix" && (
                    <>
                      <label className="v">矩阵行（id=label 每行一个）
                      </label>
                      <textarea rows={2} style={{ width: "100%" }}
                        value={(selQuestion.rows ?? []).map(
                          (o: any) => `${o.id}=${o.label}`).join("\n")}
                        onChange={(e) => updateQ(selQuestion.id, {
                          rows: e.target.value.split("\n")
                            .filter(Boolean).map((ln) => {
                              const [v, l] = ln.split("=");
                              return { id: v.trim(),
                                label: (l ?? v).trim() };
                            }) })} />
                    </>)}
                  {selQuestion.type === "rating" && (
                    <div style={{ display: "flex", gap: 6 }}>
                      <input type="number" style={{ width: 80 }}
                        value={selQuestion.min ?? 1}
                        onChange={(e) => updateQ(selQuestion.id,
                          { min: Number(e.target.value) })} />
                      <input type="number" style={{ width: 80 }}
                        value={selQuestion.max ?? 5}
                        onChange={(e) => updateQ(selQuestion.id,
                          { max: Number(e.target.value) })} />
                    </div>)}
                  {selQuestion.type === "photo" && (
                    <>
                      <label className="v">最少张数</label>
                      <input type="number" style={{ width: "100%" }}
                        value={selQuestion.min_count ?? 0}
                        onChange={(e) => updateQ(selQuestion.id,
                          { min_count: Number(e.target.value) })} />
                      <label className="v">
                        <input type="checkbox"
                          checked={!!selQuestion.require_storefront}
                          onChange={(e) => updateQ(selQuestion.id,
                            { require_storefront: e.target.checked })} />
                        {" "}门头必拍</label>
                      <label className="v">
                        <input type="checkbox"
                          checked={!!selQuestion.selfie_optional}
                          onChange={(e) => updateQ(selQuestion.id,
                            { selfie_optional: e.target.checked })} />
                        {" "}自拍可选（默认关闭人脸比对）</label>
                      <label className="v">
                        <input type="checkbox"
                          checked={!!selQuestion.recognition}
                          onChange={(e) => updateQ(selQuestion.id,
                            { recognition: e.target.checked })} />
                        {" "}识别建议（suggestion→人工 final）</label>
                      <label className="v">质量门 min_width</label>
                      <input type="number" style={{ width: "100%" }}
                        value={selQuestion.quality?.min_width ?? 0}
                        onChange={(e) => updateQ(selQuestion.id,
                          { quality: { ...(selQuestion.quality ?? {}),
                            min_width: Number(e.target.value) } })} />
                    </>)}
                  <label className="v" style={{ marginTop: 6,
                    display: "block" }}>评分权重（scoring rule weight）
                  </label>
                  <input type="number" style={{ width: "100%" }}
                    value={(spec.scoring?.rules ?? []).find(
                      (r: any) => r.question === selQuestion.id)?.weight
                      ?? 1}
                    onChange={(e) => {
                      const w = Number(e.target.value);
                      const rules = (spec.scoring?.rules ?? []).filter(
                        (r: any) => r.question !== selQuestion.id);
                      rules.push({ question: selQuestion.id, weight: w });
                      setSpec({ ...spec, scoring: {
                        ...(spec.scoring ?? {}), rules } });
                    }} />
                  <p className="v" style={{ fontSize: 11,
                    marginTop: 6 }}>
                    分值 map / 维度 / 校验在保存后的 JSON 中维护
                    （受限公式，禁任意 SQL）。</p>
                </div>)}
          </div>
        </div>)}
      {!survey && surveys.length === 0 && !err && (
        <div className="card"><EmptyState
          title="尚无问卷：点击【从空白新建】开始搭建" /></div>)}
    </>
  );
}
