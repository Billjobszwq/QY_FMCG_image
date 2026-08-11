import { useEffect, useState } from "react";
import ModuleTabs from "./ModuleTabs";

// 标注中心：Label Studio 融合页。
// - 内嵌 LS 项目 22（micro-gold 人工审核，唯一有效入口）
// - 辅助标注：ML backend（8301 级联模型）对 assisted 项目画框辅助
// - 操作逻辑四步说明
const LS = "http://127.0.0.1:8300";

export default function LabelStudioHub() {
  const [mlb, setMlb] = useState<string>("—");
  useEffect(() => {
    fetch(`${LS.replace(":8300", ":8301")}/health`)
      .then((r) => setMlb(r.ok ? "在线（辅助画框可用）" : "离线"))
      .catch(() => setMlb("离线"));
  }, []);
  return (
    <div>
      <span className="kicker">03 · 标注中心 · annotation-agent</span>
      <ModuleTabs active="/labelstudio" items={[{ to: "/labelstudio", label: "micro-gold 审核" }, { to: "/labelstudio", label: "辅助标注" }, { to: "/labelstudio", label: "操作逻辑" }]} />

      <div className="grid" style={{ marginBottom: 24 }}>
        <div className="tile" style={{ background: "var(--green)" }}>
          <span className="k">micro-gold 审核（项目 22）</span>
          <span className="num">200</span>
          <a className="btn" style={{ alignSelf: "flex-start" }}
            href={`${LS}/projects/22`} target="_blank" rel="noreferrer">
            进入审核
          </a>
        </div>
        <div className="tile" style={{ background: "var(--card-yellow)" }}>
          <span className="k">辅助标注 ML Backend</span>
          <span className="num" style={{ fontSize: 22 }}>{mlb}</span>
          <span className="k">assisted 项目自动画框 + SKU 建议</span>
        </div>
        <div className="tile" style={{ background: "var(--lavender)" }}>
          <span className="k">项目 21（旧）</span>
          <span className="num" style={{ fontSize: 22 }}>已失效</span>
          <span className="k">SUPERSEDED · 禁止审核</span>
        </div>
      </div>
      <div className="card-lg">
        <h3>标注操作逻辑（四步）</h3>
        <ol style={{ lineHeight: 1.9 }}>
          <li><b>打开任务</b>：项目 22 → 任一任务；图已裁好，无需画框。</li>
          <li><b>选 SKU</b>：点击区域 → 右侧"选择 SKU（可搜索）"输入关键词
            （如"雪碧""500ml"）→ 选中；裁切错误选
            <span className="pill warn">bad_crop</span>。</li>
          <li><b>标状态</b>：matched / unknown / conflict /
            new_packaging_* / background_no_product。</li>
          <li><b>提交</b>：Submit → 进入主审统计；确定性抽 40 条二盲，
            分歧仲裁后升级 human_final。</li>
        </ol>
        <p className="muted">
          assisted 项目（19）由 ML backend 自动画框 + SKU 建议，人工修正；
          blind 项目（20/22）无任何模型提示。
        </p>
      </div>
      <div className="card-lg" style={{ padding: 0, overflow: "hidden" }}>
        <iframe src={`${LS}/projects/22`} title="Label Studio 项目 22"
          style={{ width: "100%", height: "70vh", border: 0 }} />
      </div>
    </div>
  );
}
