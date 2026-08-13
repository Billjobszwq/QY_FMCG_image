import { useEffect, useState } from "react";
import { CapabilityInfo, fetchCapabilities, fetchVersion, HealthBody,
  iamGet } from "../api";
import { PageHeader } from "../platform/components";

export default function SystemStatus({ health }: { health: HealthBody | null }) {
  const [version, setVersion] = useState<{ platform: string; version: string } | null>(null);
  const [caps, setCaps] = useState<CapabilityInfo[] | null>(null);
  const [rlRules, setRlRules] = useState<any[] | null>(null);
  const [rlErr, setRlErr] = useState<string | null>(null);
  const [testNs, setTestNs] = useState<any | null>(null);
  const [center, setCenter] = useState<any | null>(null);
  const [gate, setGate] = useState<any | null>(null);

  useEffect(() => {
    fetchVersion().then(setVersion).catch(() => setVersion(null));
    fetchCapabilities()
      .then((b) => setCaps(b.capabilities))
      .catch(() => setCaps(null));
    // UATCC T6：限流规则与命中（仅管理员可见）
    iamGet("rate-limit/rules")
      .then((d) => setRlRules(d.rules))
      .catch((e) => { setRlRules([]);
        setRlErr(e instanceof Error ? e.message : String(e)); });
    // UFC T4/T5：测试与证据 + 机器 Gate
    iamGet("test-data/namespaces")
      .then(setTestNs).catch(() => setTestNs(null));
    // SI2 T5：测试与证据中心总览（Test Run 历史/对象计数/扫描）
    iamGet("test-data/center")
      .then(setCenter).catch(() => setCenter(null));
    fetch("/api/v1/control/gate").then((r) => r.json())
      .then(setGate).catch(() => setGate(null));
  }, []);

  return (
    <section>
      <PageHeader title="系统状态"
        desc="服务健康 / 能力 / 限流 / 测试与证据中心 / 机器 Gate（实时复评）" />
      {/* SI3（指令七.10）：可信 Gate 与阻断原因首屏展示；检查明细
          默认折叠。Gate 为实时 freshness 复评结果，非静态文件。 */}
      <div className="card">
        <h3>机器 Gate（evidence-driven，实时复评，只读）</h3>
        {/* OSV52：Active Gate 显式 Registry（gate_run_v1）——实时端点
            只读人工批准激活的 active gate run；废 mtime 选择。 */}
        <div className="v" data-testid="active-gate-panel"
          style={{ fontSize: 12, marginBottom: 8, padding: "6px 10px",
            border: "1px solid var(--border)", borderRadius: 6 }}>
          {gate?.active_gate_run ? (
            <>Active Gate：<code>
              {gate.active_gate_run.gate_run_id}</code>
              {" "}· 协议 <code>{gate.active_gate_run.protocol}</code>
              {" "}· 激活于 {gate.active_gate_run.activated_at}
              {" "}by {gate.active_gate_run.activated_by}
              {gate.active_gate_run.supersedes
                ? <> · supersedes <code>
                    {gate.active_gate_run.supersedes}</code></> : null}
              {" "}· 证据 manifest <code>
                {gate.active_gate_run.evidence_manifest_hash}</code>
            </>
          ) : (
            <>Active Gate：无（gate_run_v1 无 status=active 记录——
              实时 Gate fail-closed；需运行 gate 评估并经平台角色
              人工批准激活）</>
          )}
        </div>
        {!gate && <p className="muted">尚未生成 gate.json（运行 UAT
          --gate）</p>}
        {gate && (
          <>
            <p>
              <span className={`pill ${gate.gate ===
                "READY_FOR_REAL_DATA_UAT" ? "pill-healthy" : "pill-down"}`}>
                {gate.gate ?? "无"}</span>
              {" "}<span className="v" style={{ fontSize: 12 }}>
                evaluator {gate.evaluator_version} · commit
                {" "}{String(gate.source_commit ?? "").slice(0, 8)} ·
                {" "}{gate.evaluated_at}
                {gate.freshness_verified_at ? ` · freshness 复评于
                  ${gate.freshness_verified_at}` : ""}</span>
            </p>
            {(gate.reasons ?? []).length > 0 && (
              <ul style={{ paddingLeft: 18 }}>
                {(gate.reasons ?? []).map((r: string) => (
                  <li key={r} className="v" style={{ fontSize: 12,
                    color: "var(--err)" }}>{r}</li>))}
              </ul>)}
            <details>
              <summary className="v" style={{ fontSize: 12 }}>
                展开证据检查项（{gate.checks?.length ?? 0}）</summary>
              <table>
                <thead><tr><th>check</th><th>ok</th><th>evidence</th></tr>
                </thead>
                <tbody>
                  {(gate.checks ?? []).map((c: any) => (
                    <tr key={c.check}>
                      <td className="v">{c.check}</td>
                      <td style={{ color: c.ok ? undefined : "var(--err)" }}>
                        {c.ok ? "✓" : "✗"}</td>
                      <td className="v" style={{ fontSize: 11 }}>
                        {String(c.evidence ?? "").slice(0, 90)}</td>
                    </tr>))}
                </tbody>
              </table>
            </details>
          </>)}
      </div>
      <table>
        <tbody>
          <tr>
            <td>平台</td>
            <td>{version ? `${version.platform} v${version.version}` : "—"}</td>
          </tr>
          <tr>
            <td>统一入口</td>
            <td>http://127.0.0.1:8400</td>
          </tr>
          <tr>
            <td>整体状态</td>
            <td>
              <span className={`pill pill-${health?.status ?? "unavailable"}`}>
                {health?.status ?? "unknown"}
              </span>
            </td>
          </tr>
          <tr>
            <td>production_switch</td>
            <td>false（冻结）</td>
          </tr>
          <tr>
            <td>training_started</td>
            <td>false（冻结）</td>
          </tr>
          <tr>
            <td>deleted_files</td>
            <td>false（冻结）</td>
          </tr>
        </tbody>
      </table>
      <h3>已注册 Capability（Module Manifest）</h3>
      {caps === null ? (
        <p className="muted">加载失败或 API 不可用</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>capability_id</th>
              <th>模块</th>
              <th>版本</th>
              <th>类型</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            {caps.map((c) => (
              <tr key={c.capability_id}>
                <td>{c.capability_id}</td>
                <td>{c.module_name}</td>
                <td>{c.module_version}</td>
                <td>{c.kind}</td>
                <td className="muted">{c.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3>依赖服务明细</h3>
      <table>
        <thead>
          <tr>
            <th>服务</th>
            <th>状态</th>
            <th>detail</th>
          </tr>
        </thead>
        <tbody>
          {(health?.services ?? []).map((s) => (
            <tr key={s.name}>
              <td>{s.name}</td>
              <td>
                <span className={`pill pill-${s.status}`}>{s.status}</span>
              </td>
              <td className="muted">{s.detail ?? "ok"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>限流规则与命中（rate limit）</h3>
      {rlErr && rlRules?.length === 0 && (
        <p className="muted">仅管理员可见：{rlErr}</p>)}
      {rlRules && rlRules.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>capability</th>
              <th>窗口上限</th>
              <th>窗口(秒)</th>
              <th>burst</th>
              <th>启用</th>
              <th>累计命中</th>
            </tr>
          </thead>
          <tbody>
            {rlRules.map((r) => (
              <tr key={r.capability}>
                <td>{r.capability}</td>
                <td>{r.max_per_window}</td>
                <td>{r.window_seconds}</td>
                <td>{r.burst}</td>
                <td>{r.enabled ? "是" : "否"}</td>
                <td>{r.hits_total}</td>
              </tr>
            ))}
          </tbody>
        </table>)}

      <h3>测试与证据（UAT fixture 隔离）</h3>
      {testNs ? (
        <>
          <p className="v" style={{ fontSize: 12 }}>operational 残留：
            <strong>{testNs.operational_residue}</strong>（归档后应为
            0）；fixture 不进运营首页，仅供审计查询。</p>
          {(testNs.namespaces ?? []).length === 0
            ? <p className="v">暂无 UAT namespace</p>
            : (
              <table>
                <thead><tr><th>namespace</th><th>runs</th><th>works</th>
                  <th>可见性</th><th>最近</th></tr></thead>
                <tbody>
                  {(testNs.namespaces ?? []).slice(0, 12).map((n: any) => (
                    <tr key={n.namespace}>
                      <td className="v">{n.namespace}</td>
                      <td>{n.runs}</td>
                      <td>{n.works}</td>
                      <td style={{ color: n.visibility === "current"
                        ? "var(--accent-violet)" : undefined }}>
                        {n.visibility}</td>
                      <td className="v">
                        {String(n.last_at ?? "").slice(0, 16)}</td>
                    </tr>))}
                </tbody>
              </table>)}
        </>)
        : <p className="muted">test-data 接口不可用</p>}

      {center && (
        <>
          <h3>测试与证据中心（Test Run 全历史，可审计不可删）</h3>
          <p className="v" style={{ fontSize: 12 }}>
            一致性扫描：泄漏={JSON.stringify(
              center.scope_scan?.operational_leakage ?? {})} ·
            缺 test_run_id={center.scope_scan?.fixture_missing_test_run}
            {" "}· 父子不一致=
            {center.scope_scan?.parent_child_mismatch} ·
            待人工裁决（unresolved）={center.unresolved}
          </p>
          {(center.test_runs ?? []).length === 0
            ? <p className="v">暂无 Test Run 上下文</p>
            : (
              <table>
                <thead><tr><th>test_run_id</th><th>状态</th>
                  <th>runs</th><th>works</th><th>问卷</th><th>工作流</th>
                  <th>agent</th><th>识别</th><th>创建</th><th>归档</th>
                </tr></thead>
                <tbody>
                  {(center.test_runs ?? []).slice(0, 12).map((r: any) => (
                    <tr key={r.test_run_id}>
                      <td className="v">{r.test_run_id}</td>
                      <td style={{ color: r.status === "current"
                        ? "var(--accent-violet)" : undefined }}>
                        {r.status}</td>
                      <td>{r.objects?.runs ?? 0}</td>
                      <td>{r.objects?.work_items ?? 0}</td>
                      <td>{(r.objects?.survey_assignments ?? 0) + (
                        r.objects?.survey_responses ?? 0)}</td>
                      <td>{r.objects?.workflows ?? 0}</td>
                      <td>{r.objects?.agent_runs ?? 0}</td>
                      <td>{r.objects?.recognition_tasks ?? 0}</td>
                      <td className="v">
                        {String(r.created_at ?? "").slice(0, 16)}</td>
                      <td className="v">
                        {String(r.archived_at ?? "—").slice(0, 16)}</td>
                    </tr>))}
                </tbody>
              </table>)}
          {(center.backfill_audit ?? []).length > 0 && (
            <details>
              <summary className="v" style={{ fontSize: 12 }}>
                Legacy backfill 审计账本（
                {center.backfill_audit.length} 条）</summary>
              <table>
                <thead><tr><th>时间</th><th>表</th><th>判定依据</th>
                  <th>行数</th><th>scope</th></tr></thead>
                <tbody>
                  {(center.backfill_audit ?? []).map((a: any, i: number) => (
                    <tr key={i}>
                      <td className="v">
                        {String(a.occurred_at ?? "").slice(0, 16)}</td>
                      <td className="v">{a.table_name}</td>
                      <td className="v" style={{ fontSize: 11 }}>
                        {a.matched_by}</td>
                      <td>{a.matched_count}</td>
                      <td className="v">{a.assigned_scope}</td>
                    </tr>))}
                </tbody>
              </table>
            </details>)}
        </>)}
    </section>
  );
}
