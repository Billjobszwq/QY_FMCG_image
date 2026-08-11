import ModuleTabs from "./ModuleTabs";

// 一级模块「经营智能」：BI/告警/财务/地理/线库/问卷/策略 —— 模块化可定义。
const PLANNED = [
  { name: "BI 报表搭建", agent: "bi-agent", color: "var(--blue)",
    desc: "拖拽式报表 + 自然语言生成图表" },
  { name: "数据告警", agent: "alert-agent", color: "var(--red)",
    desc: "阈值/异常检测 → 推送告警" },
  { name: "财务对账", agent: "finance-agent", color: "var(--orange)",
    desc: "进销存与识别数据自动对账" },
  { name: "地理位置分析", agent: "geo-agent", color: "var(--green)",
    desc: "门店/货架地理维度分析" },
  { name: "线库规划", agent: "route-agent", color: "var(--violet)",
    desc: "拜访路线/库存补货规划" },
  { name: "问卷设置", agent: "survey-agent", color: "var(--yellow)",
    desc: "表单/问卷配置与回收分析" },
  { name: "数据深度对话", agent: "data-chat-agent", color: "var(--lavender)",
    desc: "自然语言查询数据仓库" },
  { name: "策略分析", agent: "strategy-agent", color: "var(--coral)",
    desc: "深度问题抽象 → 策略建议" },
];

export default function BizIntel() {
  return (
    <div>
      <span className="kicker">07 · 经营智能</span>
      <div className="display">每个模块，<br />一个 Agent。</div>
      <ModuleTabs active="/biz" items={[
        { to: "/biz", label: "模块矩阵" },
        { to: "/biz/api", label: "API 预留" },
      ]} />
      <div className="collage">
        {PLANNED.map((m) => (
          <div key={m.name} className="blk span3"
            style={{ background: m.color,
              color: /red|coral|violet|blue/.test(m.color.slice(4, 8))
                ? "#fff" : "#000" }}>
            <h2>{m.name}</h2>
            <p>{m.desc}</p>
            <span className="pill on-white">agent：{m.agent} · 待定义</span>
          </div>
        ))}
        <div className="blk c-white span12" style={{ minHeight: 0 }}>
          <h2>模块化承诺</h2>
          <p>
            新模块 = 注册 manifest（名称/色系/agent/API/数据域），
            不改底层数据架构；高级功能通过模块扩展而非兜底改库。
            每个 Agent 分工不同，后续逐个定义。
          </p>
        </div>
      </div>
    </div>
  );
}
