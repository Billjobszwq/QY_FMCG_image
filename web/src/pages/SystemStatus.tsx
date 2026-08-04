import { useEffect, useState } from "react";
import { fetchVersion, HealthBody } from "../api";

export default function SystemStatus({ health }: { health: HealthBody | null }) {
  const [version, setVersion] = useState<{ platform: string; version: string } | null>(null);

  useEffect(() => {
    fetchVersion().then(setVersion).catch(() => setVersion(null));
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
    </section>
  );
}
