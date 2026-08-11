// ABOSV2 Phase C：Workflow Studio（工作流模块七页签）。
// 搭建 / 模板库 / 运行中心 / 待办与批准 / 连接器 / Agent 与模型 /
// 证据与用量 —— 全部来自真实 API；未许可连接器诚实 blocked。
import { useEffect, useState } from "react";
import {
  WorkflowDefinition, createWorkflowDraft, fetchControlProjection,
  fetchControlReconcile, fetchNodeLibrary, fetchWorkflowRun,
  fetchWorkflows, startWorkflowRun, updateWorkflowDraft, workflowAction,
  workflowAgentDraft, workflowRunAction,
} from "../api";
import { EmptyState, ErrorState, Loading, PageHeader, StatusBadge }
  from "../platform/components";

const LIFECYCLE_CN: Record<string, string> = {
  draft: "草稿", linted: "已校验", simulated: "已模拟",
  approved: "已批准", published: "已发布", deprecated: "已弃用",
};

function useAsync<T>(fn: () => Promise<T>, deps: any[] = []): {
  data: T | null; err: string | null; reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    fn().then(setData).catch(
      (e) => setErr(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, err, reload: () => { setErr(null); setTick(t => t + 1); } };
}

// ---- 1. 工作流搭建 ----
export function WorkflowStudio() {
  const lib = useAsync(fetchNodeLibrary);
  const wfs = useAsync(fetchWorkflows);
  const [sel, setSel] = useState<WorkflowDefinition | null>(null);
  const [specText, setSpecText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nl, setNl] = useState("");

  const openDef = (d: WorkflowDefinition) => {
    setSel(d); setSpecText(JSON.stringify(d.spec, null, 2));
    setMsg(null);
  };
  const act = async (name: string,
    fn: () => Promise<any>) => {
    if (!sel || busy) return;
    setBusy(true); setMsg(null);
    try {
      const out = await fn();
      setMsg(`${name}成功`);
      setSel(out.definition ?? sel);
      wfs.reload();
    } catch (e) {
      setMsg(`${name}失败：${e instanceof Error ? e.message : e}`);
    } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="工作流搭建"
        desc="canonical 定义 · 生命周期 draft→lint→simulate→approve→publish；发布必须人工批准，修改必须新版本" />
      {lib.err && <ErrorState message={lib.err} onRetry={lib.reload} />}
      {!lib.data && !lib.err && <Loading />}
      {lib.data && (
        <div className="card">
          <h3>节点库（来自已注册 Capability / Gateway 命令，fail-closed）</h3>
          <p className="v" style={{ fontSize: 12 }}>
            节点类型：{lib.data.node_types.join(" · ")}
          </p>
          <p className="v" style={{ fontSize: 12 }}>
            可用命令/模型节点：{lib.data.command_nodes.map(
              (c) => `${c.capability}（${c.node_type}）`).join("、") || "—"}
          </p>
        </div>
      )}
      <div className="card">
        <h3>Workflow Agent（自然语言 → draft，仅预览/模拟；发布须人工）</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ flex: 1 }} value={nl}
            aria-label="自然语言工作流需求"
            placeholder="例如：帮我把这批照片识别并加人工复核"
            onChange={(e) => setNl(e.target.value)} />
          <button className="btn primary" disabled={busy || !nl.trim()}
            onClick={() => act("生成草稿", async () => {
              const out = await workflowAgentDraft(nl.trim());
              setNl(""); openDef(out.draft);
              return { definition: out.draft };
            })}>生成 draft</button>
        </div>
      </div>
      {wfs.data && wfs.data.definitions.length > 0 && (
        <div className="card">
          <h3>定义列表</h3>
          <table className="table">
            <thead><tr><th>名称</th><th>ID</th><th>版本</th><th>状态</th>
              <th>更新</th></tr></thead>
            <tbody>
              {wfs.data.definitions.map((d) => (
                <tr key={`${d.definition_id}@${d.version}`}
                  className="row-clickable" tabIndex={0}
                  onClick={() => openDef(d)}
                  onKeyDown={(e) => e.key === "Enter" && openDef(d)}>
                  <td>{d.name}</td>
                  <td className="v">{d.definition_id}</td>
                  <td>v{d.version}</td>
                  <td>{LIFECYCLE_CN[d.status] ?? d.status}</td>
                  <td className="v">{d.updated_at?.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sel && (
        <div className="card">
          <h3>编辑：{sel.name}（v{sel.version} ·
            {LIFECYCLE_CN[sel.status] ?? sel.status}）</h3>
          {sel.status !== "draft" && (
            <p className="v" style={{ fontSize: 12 }}>
              当前状态不可原地修改：请“新版本”生成 draft 后编辑。</p>
          )}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
            marginBottom: 8 }}>
            <button className="btn small" disabled={busy
              || sel.status !== "draft"}
              onClick={() => act("保存", () => updateWorkflowDraft(
                sel.definition_id, {
                  spec: JSON.parse(specText) }))}>保存 draft</button>
            <button className="btn small" disabled={busy}
              onClick={() => act("Lint", () => workflowAction(
                sel.definition_id, "lint"))}>lint</button>
            <button className="btn small" disabled={busy}
              onClick={() => act("模拟", () => workflowAction(
                sel.definition_id, "simulate", {}))}>simulate</button>
            <button className="btn small primary" disabled={busy}
              onClick={() => act("人工批准", () => workflowAction(
                sel.definition_id, "approve"))}>approve（人工）</button>
            <button className="btn small primary" disabled={busy}
              onClick={() => act("发布", () => workflowAction(
                sel.definition_id, "publish"))}>publish</button>
            <button className="btn small" disabled={busy}
              onClick={() => act("新版本", () => workflowAction(
                sel.definition_id, "new-version"))}>新版本</button>
            <button className="btn small danger" disabled={busy}
              onClick={() => act("弃用", () => workflowAction(
                sel.definition_id, "deprecate"))}>deprecate</button>
          </div>
          {(sel.lint_report ?? []).length > 0 && (
            <ul style={{ fontSize: 12 }}>
              {sel.lint_report.map((i, k) => (
                <li key={k} style={{
                  color: i.level === "error" ? "var(--err)" : "inherit" }}>
                  [{i.level}] {i.code}: {i.message}</li>
              ))}
            </ul>
          )}
          <textarea aria-label="workflow spec JSON"
            style={{ width: "100%", minHeight: 220,
              fontFamily: "var(--font-mono)", fontSize: 12 }}
            value={specText}
            onChange={(e) => setSpecText(e.target.value)} />
          {msg && <p className="v" style={{ marginTop: 6 }}>{msg}</p>}
        </div>
      )}
    </>
  );
}

// ---- 2. 模板库 ----
export function WorkflowTemplates() {
  const lib = useAsync(fetchNodeLibrary);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="模板库"
        desc="首批贯通模板：实例化为 draft，仍需 lint/模拟/人工批准后发布" />
      {lib.err && <ErrorState message={lib.err} onRetry={lib.reload} />}
      {!lib.data && !lib.err && <Loading />}
      {lib.data?.templates.map((t) => (
        <div className="card" key={t.template_id}>
          <h3>{t.name}</h3>
          <p className="v" style={{ fontSize: 12 }}>{t.template_id}</p>
          <button className="btn small primary"
            onClick={async () => {
              try {
                const out = await createWorkflowDraft(
                  { template_id: t.template_id });
                setMsg(`已实例化为 draft：${out.definition.definition_id}`
                  + "（去“工作流搭建”完成校验与人工批准）");
              } catch (e) {
                setMsg(`实例化失败：${e instanceof Error ? e.message : e}`);
              }
            }}>实例化为 draft</button>
        </div>
      ))}
      {msg && <p className="v">{msg}</p>}
    </>
  );
}

// ---- 3. 运行中心 ----
export function WorkflowRunCenter() {
  const wfs = useAsync(fetchWorkflows);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [img, setImg] = useState<File | null>(null);
  const [inputsJson, setInputsJson] = useState("{}");
  const published = (wfs.data?.definitions ?? []).filter(
    (d) => d.status === "published");

  const toB64 = (f: File) => new Promise<string>((res, rej) => {
    const rd = new FileReader();
    rd.onload = () => res(String(rd.result).split(",")[1]);
    rd.onerror = rej; rd.readAsDataURL(f);
  });

  return (
    <>
      <PageHeader title="运行中心"
        desc="published 定义可运行；checkpoint / 重试 / 取消 / 人工批准同一 run 留痕" />
      {wfs.err && <ErrorState message={wfs.err} onRetry={wfs.reload} />}
      <div className="card">
        <h3>启动运行</h3>
        {published.length === 0
          ? <EmptyState title="暂无 published 工作流"
              next="去模板库实例化并完成人工批准发布" />
          : (
            <>
              {published.map((d) => (
                <div key={d.definition_id} className="card"
                  style={{ marginBottom: 8 }}>
                  <b>{d.name}</b> <span className="v">
                    {d.definition_id} · v{d.version}</span>
                  <div style={{ display: "flex", gap: 8, marginTop: 6,
                    flexWrap: "wrap" }}>
                    <input type="file" accept="image/*"
                      aria-label="识别照片输入"
                      onChange={(e) => setImg(
                        e.target.files?.[0] ?? null)} />
                    <input style={{ flex: 1, minWidth: 200 }}
                      aria-label="其他输入 JSON" value={inputsJson}
                      onChange={(e) => setInputsJson(e.target.value)} />
                    <button className="btn small primary"
                      onClick={async () => {
                        try {
                          const extra = JSON.parse(inputsJson || "{}");
                          const inputs: Record<string, any> = { ...extra };
                          if (img) {
                            inputs.images = [[img.name, await toB64(img)]];
                          }
                          const out = await startWorkflowRun(
                            d.definition_id, inputs, d.version);
                          setRun(out);
                          setMsg(`run ${out.run.run_id} → ${out.status}`);
                        } catch (e) {
                          setMsg(`启动失败：${e instanceof Error
                            ? e.message : e}`);
                        }
                      }}>运行</button>
                  </div>
                </div>
              ))}
            </>
          )}
      </div>
      <div className="card">
        <h3>查看 run（checkpoint / 事件 / 死信）</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ flex: 1 }} value={runId}
            aria-label="run id" placeholder="run-…"
            onChange={(e) => setRunId(e.target.value)} />
          <button className="btn small" onClick={async () => {
            try { setRun(await fetchWorkflowRun(runId.trim()));
              setMsg(null); }
            catch (e) { setMsg(String(e)); }
          }}>查询</button>
        </div>
        {run?.run && (
          <>
            <p className="v">run：{run.run.run_id} ·
              状态 {run.run.status} ·
              定义 {run.run.workflow_definition_id}
              @v{run.run.workflow_version}</p>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button className="btn small" onClick={async () =>
                setRun(await workflowRunAction(
                  run.run.run_id, "pause"))}>pause</button>
              <button className="btn small" onClick={async () =>
                setRun(await workflowRunAction(
                  run.run.run_id, "resume"))}>resume</button>
              <button className="btn small danger" onClick={async () =>
                setRun(await workflowRunAction(
                  run.run.run_id, "cancel"))}>cancel</button>
              <button className="btn small" onClick={async () =>
                setRun(await workflowRunAction(
                  run.run.run_id, "retry"))}>retry 失败节点</button>
              <button className="btn small primary" onClick={async () =>
                setRun(await workflowRunAction(
                  run.run.run_id, "approve"))}>人工批准（等待节点）</button>
            </div>
            {(run.checkpoints ?? []).length > 0 && (
              <table className="table" style={{ marginTop: 8 }}>
                <thead><tr><th>节点</th><th>类型</th><th>状态</th>
                  <th>尝试</th><th>错误</th></tr></thead>
                <tbody>
                  {run.checkpoints.map((c: any) => (
                    <tr key={c.node_id}>
                      <td data-label="节点">{c.node_id}</td>
                      <td data-label="类型">{c.node_type}</td>
                      <td data-label="状态">{c.status}</td>
                      <td data-label="尝试">{c.attempts}</td>
                      <td data-label="错误" className="v"
                        style={{ fontSize: 11 }}>
                        {c.error || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {(run.dead_letters ?? []).length > 0 && (
              <p className="v" style={{ color: "var(--err)" }}>
                死信：{run.dead_letters.map((dl: any) =>
                  `${dl.node_id}: ${dl.reason}`).join("；")}</p>
            )}
          </>
        )}
        {msg && <p className="v" style={{ marginTop: 6 }}>{msg}</p>}
      </div>
    </>
  );
}

// ---- 4. 待办与批准 ----
export function WorkflowApprovals() {
  const proj = useAsync(fetchControlProjection);
  const approvals = (proj.data?.items ?? []).filter(
    (i) => ["approval", "blocked"].includes(i.status));
  return (
    <>
      <PageHeader title="待办与批准"
        desc="统一 current 投影（WorkItemV2）：人工批准与阻断事项；批准在运行中心对具体 run 执行" />
      {proj.err && <ErrorState message={proj.err} onRetry={proj.reload} />}
      {!proj.data && !proj.err && <Loading />}
      {proj.data && (approvals.length === 0
        ? <EmptyState title="当前没有待批准/阻断事项"
            next="有新的人工节点会出现在这里" />
        : (
          <table className="table">
            <thead><tr><th>work_id</th><th>状态</th><th>主题</th>
              <th>run</th></tr></thead>
            <tbody>
              {approvals.map((i: any) => (
                <tr key={i.work_id}>
                  <td data-label="work_id" className="v">{i.work_id}</td>
                  <td data-label="状态">{i.status}</td>
                  <td data-label="主题">{i.subject_id || "—"}</td>
                  <td data-label="run" className="v">{i.run_id || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ))}
      {proj.data && <p className="v" style={{ fontSize: 11 }}>
        投影 hash：{proj.data.hash.slice(0, 16)}… ·
        共 {proj.data.count} 项 current 工作</p>}
    </>
  );
}

// ---- 5. 连接器 ----
export function WorkflowConnectors() {
  const lib = useAsync(fetchNodeLibrary);
  return (
    <>
      <PageHeader title="连接器"
        desc="n8n 仅作受限 connector adapter、Dify 仅作 AI subflow adapter；ABOS 保留唯一事实源" />
      {lib.err && <ErrorState message={lib.err} onRetry={lib.reload} />}
      {!lib.data && !lib.err && <Loading />}
      {lib.data && Object.entries(lib.data.connectors).map(([name, c]) => (
        <div className="card" key={name}>
          <h3>{name} <StatusBadge
            status={c.available ? "live" : "disabled"} /></h3>
          <p className="v">{c.reason}</p>
          {!c.available && <p className="v" style={{ fontSize: 12 }}>
            诚实状态：blocked。启用前必须完成许可评估与凭据隔离设计；
            未启用期间不会执行任何外部调用。</p>}
        </div>
      ))}
    </>
  );
}

// ---- 6. Agent 与模型 ----
export function WorkflowAgentsAndModels() {
  const lib = useAsync(fetchNodeLibrary);
  return (
    <>
      <PageHeader title="Agent 与模型"
        desc="可在工作流中调用的 Agent / 模型节点（来自注册表，fail-closed）" />
      {lib.err && <ErrorState message={lib.err} onRetry={lib.reload} />}
      {lib.data && (
        <table className="table">
          <thead><tr><th>节点类型</th><th>capability</th><th>模块</th>
            <th>kind</th></tr></thead>
          <tbody>
            {lib.data.command_nodes.map((c) => (
              <tr key={c.capability}>
                <td data-label="节点类型">{c.node_type}</td>
                <td data-label="capability" className="v">{c.capability}</td>
                <td data-label="模块">{c.module}</td>
                <td data-label="kind">{c.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="card">
        <h3>说明</h3>
        <p className="v" style={{ fontSize: 12 }}>
          agent 节点在画布 spec 中以 type=agent + config.prompt 声明；
          model 节点经已注册 Capability adapter 执行。Workflow Agent
          生成 draft 只能预览/模拟，发布与高风险运行必须人工批准。</p>
      </div>
    </>
  );
}

// ---- 7. 证据与用量 ----
export function WorkflowEvidenceUsage() {
  const rec = useAsync(fetchControlReconcile);
  const proj = useAsync(fetchControlProjection);
  return (
    <>
      <PageHeader title="证据与用量"
        desc="事件↔投影↔outbox 实时对账；用量与证据沿 run 链可下钻（识别任务详情内查看）" />
      {rec.err && <ErrorState message={rec.err} onRetry={rec.reload} />}
      {!rec.data && !rec.err && <Loading />}
      {rec.data && (
        <div className="card">
          <h3>对账（reconcile）</h3>
          <p className="v">一致性：{rec.data.consistent
            ? "✅ consistent" : "❌ 不一致（需人工核查）"}</p>
          <p className="v">投影：{rec.data.projection.count} 项 ·
            hash {rec.data.projection.hash.slice(0, 16)}…</p>
          <p className="v">事件总数：{rec.data.event_count}</p>
          <p className="v">outbox：{Object.entries(rec.data.outbox).map(
            ([k, v]) => `${k}=${v}`).join("、") || "空"}</p>
        </div>
      )}
      {proj.data && (
        <div className="card">
          <h3>current 工作投影（WorkItemV2，可从事件重建）</h3>
          {proj.data.items.length === 0
            ? <EmptyState title="当前无工作项" />
            : (
              <table className="table">
                <thead><tr><th>work_id</th><th>状态</th><th>run</th>
                  <th>主题</th></tr></thead>
                <tbody>
                  {proj.data.items.map((i: any) => (
                    <tr key={i.work_id}>
                      <td data-label="work_id" className="v">{i.work_id}</td>
                      <td data-label="状态">{i.status}</td>
                      <td data-label="run" className="v">{i.run_id}</td>
                      <td data-label="主题">{i.subject_id || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      )}
    </>
  );
}
