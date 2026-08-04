export default function Assets() {
  return (
    <section>
      <h2>数据资产</h2>
      <div className="empty-state">
        <p>CAS 内容寻址存储尚未启用（M3/W8 交付）。</p>
        <p className="muted">
          旧 warehouse（.warehouse/db.sqlite）保持只读：asset 9、annotation 170、sku_catalog 28。
          新平台数据库只存 ResourceRef / 哈希 / lineage，原图目录只读不动。
        </p>
      </div>
    </section>
  );
}
