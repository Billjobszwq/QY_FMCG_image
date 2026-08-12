import { useEffect, useState } from "react";
import { CapabilityInfo, fetchCapabilities, fetchVersion, HealthBody,
  iamGet } from "../api";

export default function SystemStatus({ health }: { health: HealthBody | null }) {
  const [version, setVersion] = useState<{ platform: string; version: string } | null>(null);
  const [caps, setCaps] = useState<CapabilityInfo[] | null>(null);
  const [rlRules, setRlRules] = useState<any[] | null>(null);
  const [rlErr, setRlErr] = useState<string | null>(null);

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
    </section>
  );
}
