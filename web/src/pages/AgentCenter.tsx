// ABOSV3 T4：Agent Center —— 版本化 Agent 定义/Soul/Prompt/工具/
// Skill/KB/记忆/预算/审批的可视化工作台（draft→发布→回滚），
// health 为有界探针，测试对话走真实工具循环。
import { useCallback, useEffect, useState } from "react";
import { csrfToken } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader } from
  "../platform/components";

async function api(path: string, opts?: RequestInit) {
  const r = await fetch(`/api/v1${path}`, opts);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(`${d.detail ?? path}（HTTP ${r.status}）`);
  }
  return r.json();
}
async function post(path: string, body: unknown = {}) {
  const headers: Record<string, string> =
    { "content-type": "application/json" };
  const t = csrfToken();
  if (t) headers["X-CSRF-Token"] = t;
  return api(path, { method: "POST", headers, body: JSON.stringify(body) });
}

export default function AgentCenter() {
  const [defs, setDefs] = useState<any[] | null>(null);
  const [health, setHealth] = useState<Record<string, any>>({});
  const [sel, setSel] = useState<string>("supervisor");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [edit, setEdit] = useState({ system_prompt: "", soul: "",
    tool_allowlist: "" });
  const [assets, setAssets] = useState<any[] | null>(null);
  const [newAsset, setNewAsset] = useState({ kind: "kb", name: "",
    content: "" });
  const [memories, setMemories] = useState<any[] | null>(null);
  const [testText, setTestText] = useState("");
  const [testOut, setTestOut] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [failedRuns, setFailedRuns] = useState<any[] | null>(null);

  const load = useCallback(() => {
    api("/agents/definitions").then(async (d) => {
      setDefs(d.definitions);
      const hs: Record<string, any> = {};
      for (const x of d.definitions) {
        try {
          hs[x.agent_id] = await api(`/agents/${x.agent_id}/health`);
        } catch { hs[x.agent_id] = { healthy: false }; }
      }
      setHealth(hs);
    }).catch((e) => setErr(String(e.message ?? e)));
    // UFC T9：失败账本（failed run/evidence/error）
    api("/agents/runs?status=failed&limit=20").then(
      (d) => setFailedRuns(d.runs)).catch(() => setFailedRuns([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const d = defs?.find((x) => x.agent_id === sel);
    if (d) setEdit({
      system_prompt: d.system_prompt,
      soul: JSON.stringify(d.soul, null, 2),
      tool_allowlist: (d.tool_allowlist ?? []).join(","),
    });
    api(`/agents/${sel}/memories`).then(
      (d2) => setMemories(d2.memories)).catch(() => setMemories([]));
    setTestOut(null);
  }, [sel, defs]);

  useEffect(() => {
    api("/agents/assets").then((d) => setAssets(d.assets)).catch(
      (e) => setErr(String(e.message ?? e)));
  }, [msg]);

  const cur = defs?.find((x) => x.agent_id === sel);

  const saveDraft = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      let soul;
      try { soul = JSON.parse(edit.soul); }
      catch { throw new Error("Soul 不是合法 JSON"); }
      const d = await post(`/agents/definitions/${sel}/draft`, {
        system_prompt: edit.system_prompt, soul,
        tool_allowlist: edit.tool_allowlist.split(",")
          .map(s => s.trim()).filter(Boolean),
      });
      setMsg(`已保存 draft v${d.definition.version}（发布需人工操作）`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const publishLatest = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const d = await post(`/agents/definitions/${sel}/publish`, {});
      setMsg(`已发布 ${sel} v${d.definition.version}`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const rollback = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const d = await post(`/agents/definitions/${sel}/rollback`, {});
      setMsg(`已回滚到 v${d.definition.version}`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const runTest = async () => {
    if (!testText.trim()) return;
    setBusy(true); setErr(null);
    try {
      setTestOut(await post(`/agents/${sel}/invoke`,
        { text: testText }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Agent Center"
        desc="版本化定义（Soul/Prompt/工具/预算/审批）· 有界 health 探针 · Skill/Prompt/KB 资产 · 记忆 ACL · 真实工具循环测试" />
      {err && <ErrorState message={err} onRetry={() => {
        setErr(null); load(); }} />}
      {msg && <div className="banner banner-info">{msg}</div>}

      <div className="card">
        <h3>Agent 列表（health = 有界探针，非 Manifest 存在即健康）</h3>
        {!defs && !err && <Loading text="加载 Agent 定义…" />}
        {defs && (
          <table className="table">
            <thead><tr><th>Agent</th><th>版本/状态</th><th>Health</th>
              <th>工具数</th><th>选择</th></tr></thead>
            <tbody>
              {defs.map((d) => (
                <tr key={d.agent_id}>
                  <td data-label="Agent">{d.agent_id}</td>
                  <td data-label="版本">v{d.version} · {d.status}</td>
                  <td data-label="Health">
                    <span className={health[d.agent_id]?.healthy
                      ? "pill-healthy" : "pill-unavailable"}>
                      {health[d.agent_id]?.healthy ? "healthy"
                        : (health[d.agent_id]?.status ?? "unknown")}
                    </span></td>
                  <td data-label="工具数">{d.tool_allowlist?.length}</td>
                  <td data-label="选择">
                    <button className="btn small"
                      onClick={() => setSel(d.agent_id)}>打开</button></td>
                </tr>))}
            </tbody>
          </table>)}
      </div>

      {cur && (
        <div className="grid" style={{ gridTemplateColumns:
          "repeat(auto-fit, minmax(340px, 1fr))" }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>{sel} · 定义编辑（保存=新 draft）</h3>
            <p className="v">状态 {cur.status} · provider
              {" "}{cur.provider} · 预算
              {" "}{JSON.stringify(cur.budget)} · 审批
              {" "}{JSON.stringify(cur.approval)}</p>
            <label className="v">Soul（长期身份/价值边界，JSON）</label>
            <textarea rows={4} style={{ width: "100%" }}
              aria-label="Soul" value={edit.soul}
              onChange={(e) => setEdit({ ...edit, soul: e.target.value })} />
            <label className="v">System Prompt（具体指令；不得含密钥）</label>
            <textarea rows={3} style={{ width: "100%" }}
              aria-label="System Prompt" value={edit.system_prompt}
              onChange={(e) => setEdit({ ...edit,
                system_prompt: e.target.value })} />
            <label className="v">工具 allowlist（逗号分隔）</label>
            <input style={{ width: "100%" }} aria-label="工具 allowlist"
              value={edit.tool_allowlist}
              onChange={(e) => setEdit({ ...edit,
                tool_allowlist: e.target.value })} />
            <div style={{ display: "flex", gap: 8, marginTop: 8,
              flexWrap: "wrap" }}>
              <button className="btn" disabled={busy}
                onClick={saveDraft}>保存 draft</button>
              <button className="btn primary" disabled={busy}
                onClick={publishLatest}>发布最新 draft</button>
              <button className="btn danger" disabled={busy}
                onClick={rollback}>回滚上一版</button>
            </div>
            <h3 style={{ marginTop: 12 }}>测试（真实工具循环）</h3>
            <div style={{ display: "flex", gap: 6 }}>
              <input style={{ flex: 1 }} value={testText}
                aria-label="测试意图"
                placeholder="例如：项目进度做到哪里了？"
                onChange={(e) => setTestText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runTest(); }} />
              <button className="btn primary" disabled={busy}
                onClick={runTest}>{busy ? "运行中…" : "发送"}</button>
            </div>
            {testOut && (
              <div style={{ marginTop: 8 }}>
                <p className="v">provider: {testOut.provider}
                  {testOut.degraded ? "（degraded）" : ""} · run
                  {testOut.run_id ? ` ${testOut.run_id}` : ""}</p>
                <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                  {testOut.message}</pre>
                {(testOut.tool_trace ?? []).map((t: any, i: number) => (
                  <p key={i} className="v">工具 {t.tool} → {t.status}
                    {t.elapsed_ms ? `（${t.elapsed_ms}ms）` : ""}
                    {t.reason ? ` · ${t.reason}` : ""}
                    {t.error ? ` · ${t.error}` : ""}</p>))}
                {(testOut.command_previews ?? []).map((cp: any) => (
                  <div key={cp.command_id} className="cmd-preview">
                    <div className="row"><b>待批准命令</b>
                      <span>{cp.command_id} · {cp.kind}</span></div>
                    <div className="row"><b>影响</b>
                      <span>{cp.impact}</span></div>
                  </div>))}
              </div>)}
          </div>

          <div className="card" style={{ marginBottom: 0 }}>
            <h3>记忆（ACL 控制，人工可清除）</h3>
            {memories === null ? <Loading /> :
              memories.length === 0
                ? <EmptyState title="暂无记忆条目" />
                : memories.map((m) => (
                  <div key={m.memory_id} className="note-card"
                    style={{ display: "flex",
                      justifyContent: "space-between", gap: 6 }}>
                    <span>[{m.level}] {m.content}</span>
                    <button className="btn small" onClick={async () => {
                      const headers: Record<string, string> = {};
                      const t = csrfToken();
                      if (t) headers["X-CSRF-Token"] = t;
                      await api(`/agents/memories/${m.memory_id}`,
                        { method: "DELETE", headers });
                      const d2 = await api(`/agents/${sel}/memories`);
                      setMemories(d2.memories);
                    }}>清除</button>
                  </div>))}
          </div>
        </div>)}

      <div className="card">
        <h3>Skill / Prompt / 知识库资产（draft→发布；draft 不可被检索）</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <select value={newAsset.kind} aria-label="资产类型"
            onChange={(e) => setNewAsset({ ...newAsset,
              kind: e.target.value })}>
            <option value="kb">知识库 KB</option>
            <option value="skill">Skill</option>
            <option value="prompt">Prompt</option>
          </select>
          <input placeholder="名称" aria-label="资产名称"
            value={newAsset.name}
            onChange={(e) => setNewAsset({ ...newAsset,
              name: e.target.value })} />
          <input placeholder="内容" style={{ flex: 1, minWidth: 200 }}
            aria-label="资产内容" value={newAsset.content}
            onChange={(e) => setNewAsset({ ...newAsset,
              content: e.target.value })} />
          <button className="btn primary" disabled={busy
            || !newAsset.name || !newAsset.content}
            onClick={async () => {
              setBusy(true); setMsg(null);
              try {
                await post("/agents/assets", newAsset);
                setMsg("资产已保存为 draft");
                setNewAsset({ ...newAsset, name: "", content: "" });
              } catch (e) {
                setErr(e instanceof Error ? e.message : String(e));
              } finally { setBusy(false); }
            }}>保存 draft</button>
        </div>
        {assets === null ? <Loading /> : assets.length === 0
          ? <EmptyState title="暂无资产" />
          : (
            <table className="table">
              <thead><tr><th>类型</th><th>名称</th><th>版本</th>
                <th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {assets.map((a) => (
                  <tr key={`${a.asset_id}@${a.version}`}>
                    <td data-label="类型">{a.kind}</td>
                    <td data-label="名称">{a.name}</td>
                    <td data-label="版本">v{a.version}</td>
                    <td data-label="状态">{a.status}</td>
                    <td data-label="操作">
                      {a.status === "draft" && (
                        <button className="btn small" onClick={async () => {
                          setMsg(null);
                          try {
                            await post(
                              `/agents/assets/${a.asset_id}/publish`, {});
                            setMsg(`已发布 ${a.name}`);
                          } catch (e) {
                            setErr(e instanceof Error
                              ? e.message : String(e));
                          }
                        }}>发布</button>)}
                    </td>
                  </tr>))}
              </tbody>
            </table>)}
      </div>

      <div className="card">
        <h3>失败账本（Agent failed runs）</h3>
        <p className="v" style={{ fontSize: 12 }}>定义缺失/工具失败也进
          统一调用链：failed BusinessRun + blocked WorkItem + Evidence
          + Usage；失败状态不用成功色。</p>
        {failedRuns && failedRuns.length === 0 && (
          <p className="v">暂无失败 Agent 运行</p>)}
        {failedRuns && failedRuns.length > 0 && (
          <table className="table">
            <thead><tr><th>run</th><th>agent</th><th>状态</th>
              <th>error</th><th>evidence</th><th>时间</th></tr></thead>
            <tbody>
              {failedRuns.map((r) => (
                <tr key={r.run_id}>
                  <td data-label="run" className="v">
                    {String(r.business_run_id || r.run_id)
                      .slice(0, 16)}…</td>
                  <td data-label="agent">{r.agent_id}</td>
                  <td data-label="状态"
                    style={{ color: "var(--err)" }}>
                    {r.business_status || r.status}</td>
                  <td data-label="error" className="v"
                    style={{ fontSize: 11 }}>
                    {(r.error || "").slice(0, 60) || "—"}</td>
                  <td data-label="evidence" className="v"
                    style={{ fontSize: 11 }}>
                    {String(r.evidence_bundle_id || "—").slice(0, 16)}
                  </td>
                  <td data-label="时间" className="v">
                    {String(r.created_at).slice(0, 16)}</td>
                </tr>))}
            </tbody>
          </table>)}
      </div>
    </>
  );
}
