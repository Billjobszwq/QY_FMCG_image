import { useEffect, useState } from "react";
import { CapabilityInfo, fetchCapabilities, fetchVersion, HealthBody,
  iamGet } from "../api";

export default function SystemStatus({ health }: { health: HealthBody | null }) {
  const [version, setVersion] = useState<{ platform: string; version: string } | null>(null);
  const [caps, setCaps] = useState<CapabilityInfo[] | null>(null);
  const [rlRules, setRlRules] = useState<any[] | null>(null);
  const [rlErr, setRlErr] = useState<string | null>(null);
  const [testNs, setTestNs] = useState<any | null>(null);
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
    fetch("/api/v1/control/gate").then((r) => r.json())
      .then(setGate).catch(() => setGate(null));
  }, []);

  return (
    <section>
      <h2>系统状态</h2>
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

      <h3>机器 Gate（evidence-driven，只读）</h3>
      {!gate && <p className="muted">尚未生成 gate.json（运行 UAT V3
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
              {" "}{gate.evaluated_at}</span>
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
    </section>
  );
}
