// 二级菜单：模块内功能页签（三级操作在页内）。
export default function ModuleTabs({ items, active }:
  { items: { to: string; label: string }[]; active: string }) {
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap",
      margin: "0 0 22px" }}>
      {items.map((t) => (
        <a key={t.to} href={`#${t.to}`}
          className="pill"
          style={{ background: active === t.to ? "#000" : "#fff",
            color: active === t.to ? "#fff" : "#000",
            textDecoration: "none", padding: "8px 18px" }}>
          {t.label}
        </a>
      ))}
    </div>
  );
}
