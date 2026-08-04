import { HealthBody } from "../api";

export default function Overview({ health }: { health: HealthBody | null }) {
  if (!health) return <p className="muted">正在加载系统状态…</p>;
  const down = health.services.filter((s) => s.status !== "healthy");
  return (
    <section>
      <h2>系统总览</h2>
      <div className="cards">
        <div className={`card card-${health.status}`}>
          <div className="k">平台整体状态</div>
          <div className="v">{health.status}</div>
        </div>
        <div className="card">
          <div className="k">受监控服务</div>
          <div className="v">{health.services.length}</div>
        </div>
        <div className="card">
          <div className="k">异常服务</div>
          <div className="v">{down.length}</div>
        </div>
      </div>
      <h3>服务状态</h3>
      <table>
        <thead>
          <tr>
            <th>服务</th>
            <th>状态</th>
            <th>延迟</th>
            <th>关键</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {health.services.map((s) => (
            <tr key={s.name}>
              <td>{s.name}</td>
              <td>
                <span className={`pill pill-${s.status}`}>{s.status}</span>
              </td>
              <td>{s.latency_ms != null ? `${s.latency_ms} ms` : "—"}</td>
              <td>{s.critical ? "是" : "否"}</td>
              <td className="muted">{s.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {down.length > 0 && (
        <div className="note">
          真实阻断项：{down.map((s) => `${s.name}（${s.detail ?? s.status}）`).join("；")}
        </div>
      )}
      <p className="muted">健康快照时间：{health.generated_at}</p>
    </section>
  );
}
