// ABOSV3 T5：React Flow 可视化 Workflow Studio（默认拖拽画布；
// JSON 仅作高级视图）。Palette 来自 Registry 投影；保存为 ABOS
// canonical graph（ui 坐标不参与 hash）；lint/simulate/test-run/
// approve/publish/新版本；运行面板支持暂停/恢复/取消/重试/人工批准。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background, Controls, MiniMap, ReactFlow, ReactFlowProvider,
  addEdge, applyEdgeChanges, applyNodeChanges,
  type Connection, type Edge, type EdgeChange, type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  createWorkflowDraft, fetchNodeLibrary, fetchWorkflow, fetchWorkflows,
  startWorkflowRun, updateWorkflowDraft, workflowAction,
  workflowRunAction,
} from "../api";
import { ErrorState, Loading, PageHeader } from "../platform/components";

const NODE_LABEL: Record<string, string> = {
  trigger: "触发器", command: "领域命令", query: "查询",
  condition: "条件", transform: "转换", agent: "Agent", model: "模型",
  human_approval: "人工批准", wait: "等待/定时", loop: "循环",
  parallel: "并行", join: "汇合", subflow: "子流程",
  connector: "连接器", end: "结束",
};
const NODE_COLOR: Record<string, string> = {
  trigger: "#2f7d4f", end: "#6b7280", command: "#2563eb",
  condition: "#b45309", transform: "#0e7490", agent: "#7c3aed",
  model: "#7c3aed", human_approval: "#ca8a04", wait: "#0891b2",
  loop: "#c2410c", parallel: "#4338ca", join: "#4338ca",
  subflow: "#0f766e", connector: "#52525b", query: "#0369a1",
};

// canonical spec → React Flow 元素
function specToFlow(spec: any): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = (spec?.nodes ?? []).map((n: any, i: number) => ({
    id: n.id,
    position: { x: n.ui?.x ?? 80 + (i % 4) * 200,
      y: n.ui?.y ?? 80 + Math.floor(i / 4) * 120 },
    data: { label: `${NODE_LABEL[n.type] ?? n.type}\n${n.id}` },
    style: { background: "#fff", color: "#111",
      border: `2px solid ${NODE_COLOR[n.type] ?? "#999"}`,
      borderRadius: 8, padding: "6px 10px", fontSize: 12,
      whiteSpace: "pre" as const },
  }));
  // condition 的规则分支也画出来
  const edges: Edge[] = (spec?.edges ?? []).map((e: any, i: number) => ({
    id: `e${i}-${e.from}-${e.to}`, source: e.from, target: e.to,
  }));
  for (const n of spec?.nodes ?? []) {
    if (n.type === "condition") {
      for (const r of n.config?.rules ?? []) {
        if (r.to) edges.push({ id: `rule-${n.id}-${r.to}`,
          source: n.id, target: r.to, label: String(r.when?.op ?? ""),
          style: { strokeDasharray: "4 3" } });
      }
    }
  }
  return { nodes, edges };
}

// React Flow 元素 → canonical spec（保留配置，更新 ui 坐标与边）
function flowToSpec(nodes: Node[], edges: Edge[],
  prevSpec: any): any {
  const prevNodes: Record<string, any> = {};
  for (const n of prevSpec?.nodes ?? []) prevNodes[n.id] = n;
  const specNodes = nodes.map((n) => {
    const prev = prevNodes[n.id] ?? { id: n.id, type: "transform",
      config: {} };
    return { ...prev, id: n.id,
      ui: { x: Math.round(n.position.x), y: Math.round(n.position.y) } };
  });
  const specEdges = edges.filter((e) => !String(e.id)
    .startsWith("rule-")).map((e) => ({ from: e.source, to: e.target }));
  return { ...(prevSpec ?? {}), trigger: prevSpec?.trigger
    ?? { type: "manual" }, variables: prevSpec?.variables ?? {},
    nodes: specNodes, edges: specEdges, policy: prevSpec?.policy
    ?? { approval_required_for_publish: true } };
}

function CanvasInner() {
  const [library, setLibrary] = useState<any | null>(null);
  const [defs, setDefs] = useState<any[]>([]);
  const [selId, setSelId] = useState<string>("");
  const [def, setDef] = useState<any | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selNode, setSelNode] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"canvas" | "json">("canvas");
  const [runOut, setRunOut] = useState<any | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchNodeLibrary().then(setLibrary).catch(
      (e) => setErr(String(e.message ?? e)));
    fetchWorkflows().then((d) => {
      setDefs(d.definitions);
      const latest = new Map<string, any>();
      for (const x of d.definitions) {
        const k = x.definition_id;
        if (!latest.has(k) || latest.get(k).version < x.version) {
          latest.set(k, x);
        }
      }
      const arr = [...latest.values()];
      setDefs(arr);
      if (arr.length) { setSelId(arr[0].definition_id); }
    }).catch((e) => setErr(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    if (!selId) return;
    fetchWorkflow(selId).then((d) => {
      setDef(d.definition);
      const f = specToFlow(d.definition.spec);
      setNodes(f.nodes); setEdges(f.edges);
    }).catch((e) => setErr(String(e.message ?? e)));
  }, [selId]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((ns) => applyNodeChanges(changes, ns));
  }, []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((es) => applyEdgeChanges(changes, es));
  }, []);
  const onConnect = useCallback((c: Connection) => {
    setEdges((es) => addEdge({ ...c,
      id: `e-${Date.now()}` }, es));
  }, []);

  const onDrop = useCallback((ev: React.DragEvent) => {
    ev.preventDefault();
    const type = ev.dataTransfer.getData("application/abos-node");
    if (!type || !wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const id = `${type}-${Math.random().toString(36).slice(2, 7)}`;
    const node: Node = {
      id, type: "default",
      position: { x: ev.clientX - rect.left - 60,
        y: ev.clientY - rect.top - 20 },
      data: { label: `${NODE_LABEL[type] ?? type}\n${id}` },
      style: { background: "#fff", color: "#111",
        border: `2px solid ${NODE_COLOR[type] ?? "#999"}`,
        borderRadius: 8, padding: "6px 10px", fontSize: 12,
        whiteSpace: "pre" as const },
    };
    setNodes((ns) => [...ns, node]);
    // 新节点默认类型写入 spec（保存时生效）
    setDef((d: any) => d ? { ...d,
      spec: { ...d.spec, nodes: [...(d.spec.nodes ?? []),
        { id, type, config: {} }] } } : d);
  }, []);

  const saveDraft = async () => {
    if (!def) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const spec = flowToSpec(nodes, edges, def.spec);
      const d = await updateWorkflowDraft(def.definition_id, { spec });
      setDef(d.definition);
      setMsg(`已保存 draft v${d.definition.version}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const act = async (action: "lint" | "simulate" | "approve"
    | "publish" | "new-version") => {
    if (!def) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      await saveDraft();
      const r = await workflowAction(def.definition_id, action,
        action === "simulate" ? {} : undefined);
      setMsg(`${action} 完成`);
      if (action === "lint" && r.definition?.lint_report) {
        setRunOut({ lint: r.definition.lint_report });
      }
      const d = await fetchWorkflow(def.definition_id);
      setDef(d.definition);
      fetchWorkflows().then((x) => setDefs(x.definitions));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const testRun = async () => {
    if (!def) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      await saveDraft();
      const r = await startWorkflowRun(def.definition_id, {});
      setRunOut(r);
      setMsg(`运行 ${r.run?.run_id ?? ""} → ${r.run?.status ?? ""}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const createBlank = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await createWorkflowDraft({
        name: `画布草稿 ${new Date().toLocaleString()}`,
        spec: { trigger: { type: "manual" }, variables: {},
          nodes: [{ id: "start", type: "trigger",
            ui: { x: 60, y: 120 } },
          { id: "end", type: "end", ui: { x: 420, y: 120 } }],
          edges: [{ from: "start", to: "end" }],
          policy: { approval_required_for_publish: true } },
      });
      setMsg(`已创建 ${d.definition.definition_id}`);
      fetchWorkflows().then((x) => setDefs(x.definitions));
      setSelId(d.definition.definition_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  };

  const selSpecNode = useMemo(() => (def?.spec?.nodes ?? []).find(
    (n: any) => n.id === selNode), [def, selNode]);

  const updateNodeConfig = (key: string, value: any) => {
    if (!selSpecNode) return;
    setDef((d: any) => ({ ...d, spec: { ...d.spec,
      nodes: d.spec.nodes.map((n: any) => n.id === selSpecNode.id
        ? { ...n, config: { ...(n.config ?? {}), [key]: value } } : n) } }));
  };

  if (err && !def) return <ErrorState message={err}
    onRetry={() => { setErr(null); }} />;

  return (
    <>
      <PageHeader title="工作流搭建（React Flow 画布）"
        desc="拖拽搭建 → lint → 模拟 → 人工批准 → 发布 → 测试运行；canonical graph 保存，JSON 仅高级视图" />
      {msg && <div className="banner banner-info">{msg}</div>}
      {err && <div className="banner banner-error">{err}</div>}

      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
          alignItems: "center" }}>
          <select value={selId} aria-label="选择工作流"
            onChange={(e) => setSelId(e.target.value)}>
            {defs.map((d) => (
              <option key={d.definition_id} value={d.definition_id}>
                {d.name}（{d.definition_id} v{d.version} ·
                {" "}{d.status}）</option>))}
          </select>
          <button className="btn" onClick={createBlank}
            disabled={busy}>新建空白</button>
          <button className="btn" onClick={saveDraft} disabled={busy}>
            保存 draft</button>
          <button className="btn" onClick={() => act("lint")}
            disabled={busy}>lint</button>
          <button className="btn" onClick={() => act("simulate")}
            disabled={busy}>模拟</button>
          <button className="btn" onClick={() => act("approve")}
            disabled={busy}>人工批准</button>
          <button className="btn primary" onClick={() => act("publish")}
            disabled={busy}>发布</button>
          <button className="btn" onClick={() => act("new-version")}
            disabled={busy}>新版本</button>
          <button className="btn primary" onClick={testRun}
            disabled={busy}>测试运行</button>
          <span style={{ flex: 1 }} />
          <button className="btn small"
            onClick={() => setView(view === "canvas" ? "json" : "canvas")}>
            {view === "canvas" ? "JSON 高级视图" : "返回画布"}</button>
        </div>
        {def && <p className="v" style={{ marginTop: 6 }}>
          状态 {def.status} · hash {String(def.spec_hash ?? "")
            .slice(0, 12)}…（UI 坐标不参与 hash）
          {def.status === "published" && " · 已发布版本不可原地修改，请新版本"}
        </p>}
      </div>

      {view === "json" ? (
        <div className="card">
          <h3>JSON 高级视图（只读展示 canonical graph；编辑请用画布）</h3>
          <pre style={{ fontSize: 12, overflowX: "auto" }}>
            {JSON.stringify(def?.spec ?? {}, null, 2)}</pre>
        </div>
      ) : (
        <div style={{ display: "grid",
          gridTemplateColumns: "190px minmax(420px, 1fr) 260px",
          gap: 12, overflowX: "auto" }}>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>节点库（Registry 投影）</h3>
            {!library ? <Loading /> : library.node_types.map((t: string) => (
              <div key={t} draggable
                onDragStart={(e) => e.dataTransfer.setData(
                  "application/abos-node", t)}
                className="note-card"
                style={{ cursor: "grab", borderLeft: `4px solid ${
                  NODE_COLOR[t] ?? "#999"}` }}>
                {NODE_LABEL[t] ?? t} <span className="meta">{t}</span>
              </div>))}
            {library && (
              <p className="v" style={{ fontSize: 11 }}>
                命令节点：{library.command_nodes.map(
                  (cn: any) => cn.capability).join("、")}
                {Object.entries(library.connectors).map(([k, v]: any) =>
                  v.available ? "" : `；连接器 ${k} blocked`)}
              </p>)}
          </div>
          <div ref={wrapRef} onDrop={onDrop}
            onDragOver={(e) => e.preventDefault()}
            style={{ height: 520, minWidth: 420,
              border: "1px solid var(--border)",
              borderRadius: 8, overflow: "hidden" }}>
            <ReactFlowProvider>
              <ReactFlow nodes={nodes} edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange} onConnect={onConnect}
                onNodeClick={(_, n) => setSelNode(n.id)}
                fitView deleteKeyCode={["Backspace", "Delete"]}>
                <Background />
                <MiniMap />
                <Controls />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
          <div className="card" style={{ marginBottom: 0 }}>
            <h3>Inspector</h3>
            {!selSpecNode
              ? <p className="v">选中画布节点后可编辑配置</p>
              : (
                <div>
                  <p className="v"><b>{selSpecNode.id}</b>
                    {" "}（{selSpecNode.type}）</p>
                  {selSpecNode.type === "wait" && (
                    <>
                      <label className="v">等待秒数</label>
                      <input style={{ width: "100%" }} type="number"
                        value={selSpecNode.config?.seconds ?? 0}
                        onChange={(e) => updateNodeConfig("seconds",
                          Number(e.target.value))} />
                    </>)}
                  {selSpecNode.type === "join" && (
                    <>
                      <label className="v">汇合模式</label>
                      <select style={{ width: "100%" }}
                        value={selSpecNode.config?.mode ?? "all"}
                        onChange={(e) => updateNodeConfig("mode",
                          e.target.value)}>
                        <option value="all">all（全部分支）</option>
                        <option value="any">any（任一分支）</option>
                        <option value="quorum">quorum（法定人数）</option>
                      </select>
                      {selSpecNode.config?.mode === "quorum" && (
                        <>
                          <label className="v">quorum 数</label>
                          <input style={{ width: "100%" }} type="number"
                            value={selSpecNode.config?.quorum ?? 1}
                            onChange={(e) => updateNodeConfig("quorum",
                              Number(e.target.value))} />
                        </>)}
                    </>)}
                  {selSpecNode.type === "agent" && (
                    <>
                      <label className="v">指定 Agent</label>
                      <input style={{ width: "100%" }}
                        value={selSpecNode.config?.agent_id ?? ""}
                        placeholder="如 analytics_agent"
                        onChange={(e) => updateNodeConfig("agent_id",
                          e.target.value)} />
                      <label className="v">提示词</label>
                      <input style={{ width: "100%" }}
                        value={selSpecNode.config?.prompt ?? ""}
                        onChange={(e) => updateNodeConfig("prompt",
                          e.target.value)} />
                    </>)}
                  {(selSpecNode.type === "command"
                    || selSpecNode.type === "model") && (
                    <>
                      <label className="v">capability</label>
                      <select style={{ width: "100%" }}
                        value={selSpecNode.capability ?? ""}
                        onChange={(e) => setDef((d: any) => ({ ...d,
                          spec: { ...d.spec, nodes: d.spec.nodes.map(
                            (n: any) => n.id === selSpecNode.id
                              ? { ...n, capability: e.target.value }
                              : n) } }))}>
                        <option value="">选择已注册命令…</option>
                        {(library?.command_nodes ?? []).map((cn: any) => (
                          <option key={cn.capability}
                            value={cn.capability}>{cn.capability}
                          </option>))}
                      </select>
                    </>)}
                  {selSpecNode.type === "loop" && (
                    <>
                      <label className="v">items_path</label>
                      <input style={{ width: "100%" }}
                        value={selSpecNode.config?.items_path ?? ""}
                        placeholder="$inputs.items"
                        onChange={(e) => updateNodeConfig("items_path",
                          e.target.value)} />
                      <label className="v">body 节点 ID</label>
                      <input style={{ width: "100%" }}
                        value={selSpecNode.config?.body ?? ""}
                        onChange={(e) => updateNodeConfig("body",
                          e.target.value)} />
                    </>)}
                  {selSpecNode.type === "human_approval" && (
                    <>
                      <label className="v">批准标题</label>
                      <input style={{ width: "100%" }}
                        value={selSpecNode.config?.title ?? ""}
                        onChange={(e) => updateNodeConfig("title",
                          e.target.value)} />
                    </>)}
                  <p className="v" style={{ marginTop: 8, fontSize: 11 }}>
                    policy（retry/timeout/approval）在 JSON 高级视图中维护
                  </p>
                </div>)}
          </div>
        </div>)}

      {runOut && (
        <div className="card">
          <h3>运行面板</h3>
          {runOut.lint && (
            <div>
              {runOut.lint.length === 0
                ? <p className="v">lint 通过（无错误）</p>
                : runOut.lint.map((i: any, k: number) => (
                  <p key={k} className="v" style={{
                    color: i.level === "error" ? "var(--err)"
                      : "var(--warn)" }}>
                    [{i.level}] {i.code}: {i.message}</p>))}
            </div>)}
          {runOut.run && (
            <div>
              <p className="v">run {runOut.run.run_id} ·
                状态 <b>{runOut.run.status}</b>
                {runOut.run.error ? ` · 错误 ${runOut.run.error}` : ""}</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
                marginTop: 6 }}>
                <button className="btn small" onClick={async () => {
                  setRunOut(await workflowRunAction(
                    runOut.run.run_id, "pause"));
                }}>暂停</button>
                <button className="btn small" onClick={async () => {
                  setRunOut(await workflowRunAction(
                    runOut.run.run_id, "resume"));
                }}>恢复</button>
                <button className="btn small" onClick={async () => {
                  setRunOut(await workflowRunAction(
                    runOut.run.run_id, "approve"));
                }}>批准等待节点</button>
                <button className="btn small" onClick={async () => {
                  setRunOut(await workflowRunAction(
                    runOut.run.run_id, "retry"));
                }}>重试</button>
                <button className="btn small danger" onClick={async () => {
                  setRunOut(await workflowRunAction(
                    runOut.run.run_id, "cancel"));
                }}>取消</button>
              </div>
              {(runOut.trace?.nodes) && (
                <p className="v" style={{ marginTop: 6 }}>
                  节点轨迹：{Object.keys(runOut.trace.nodes).join(" → ")}
                </p>)}
            </div>)}
        </div>)}
    </>
  );
}

export default function WorkflowCanvas() {
  return <CanvasInner />;
}
