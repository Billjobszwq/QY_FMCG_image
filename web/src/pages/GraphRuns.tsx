export default function GraphRuns() {
  return (
    <section>
      <h2>Graph Runs</h2>
      <div className="empty-state">
        <p>Graph Runtime 尚未启用（M3 交付）。</p>
        <p className="muted">
          M3 将提供 fmcg_photo_inspection_v1 与 system_health_v1 两条真实 Graph，
          此页将展示 Run 列表、节点时间线、检查点与证据。
        </p>
      </div>
    </section>
  );
}
