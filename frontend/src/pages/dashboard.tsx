/**
 * 仪表盘页面（窗口内容组件，不含窗口壳）。
 *
 * 信息密度优先：E0 基线四指标 + 每日照片量 + 识别结果构成 + 级联漏斗。
 * 数据全部来自样本层（src/data/sample.ts），明显标注"样本"口径。
 *
 * 设计红线自查：
 * —— 无渐变背景 / 无毛玻璃；橙色 accent 未作任何静态装饰
 * —— 颜色一律走 @theme 令牌（系列色经原语以 var(--color-*) 传入）
 * —— 文本仅 text-primary / text-secondary；数值/标签/图例不穿系列色
 */
import {
  BASELINE,
  DAILY,
  FUNNEL,
} from "@/data/sample";
import {
  ChartCard,
  HBars,
  StatTile,
  StackedBars,
  VBars,
} from "@/components/charts/primitives";

/** 日期压缩为 MM-DD（X 轴标签，14 天序列） */
function shortDay(iso: string): string {
  return iso.slice(5);
}

/** 千分位格式化（页脚/aside 等原语之外的文案用） */
function fmt(n: number): string {
  return n.toLocaleString("zh-CN");
}

/** 漏斗首段总量：后续各阶段占比的分母（FUNNEL 单调递减，首段即照片总量） */
const FUNNEL_TOTAL = FUNNEL[0].value;

/** 漏斗数据：标签侧附带"占首段百分比"，条右直接标签为张数（HBars 原语口径） */
const FUNNEL_DATA = FUNNEL.map((s) => ({
  label: `${s.label} ${((s.value / FUNNEL_TOTAL) * 100).toFixed(1)}%`,
  value: s.value,
}));

/** 每日照片量（单系列竖条，标题即系列名，不加图例） */
const DAILY_PHOTOS = DAILY.map((d) => ({
  label: shortDay(d.date),
  value: d.photos,
}));

/** 识别结果构成：三系列堆叠，类目序固定 series-1 蓝 → 2 黄 → 3 紫 */
const RESULT_LABELS = DAILY.map((d) => shortDay(d.date));
const RESULT_SERIES = [
  { name: "accepted", color: "var(--color-series-1)", values: DAILY.map((d) => d.accepted) },
  { name: "review", color: "var(--color-series-2)", values: DAILY.map((d) => d.review) },
  { name: "rejected", color: "var(--color-series-3)", values: DAILY.map((d) => d.rejected) },
];

/** 产品仪表盘内容（default export，由桌面窗口壳装载） */
export default function DashboardContent() {
  return (
    <div className="space-y-4 p-5">
      {/* ---- 1) E0 基线指标行 ---- */}
      <div className="grid grid-cols-4 gap-3">
        <StatTile
          label="accepted precision"
          value={`${BASELINE.acceptedPrecisionPct.toFixed(1)}%`}
          note={`E0 · ${BASELINE.evalSet} n=${BASELINE.evalSize}`}
        />
        <StatTile
          label="端到端召回"
          value={`${BASELINE.endToEndRecallPct.toFixed(1)}%`}
          note="accepted 且正确 / GT"
        />
        <StatTile
          label="进入 review"
          value={`${BASELINE.reviewRatioPct.toFixed(1)}%`}
          note="已匹配口径"
        />
        <StatTile
          label="FP 每照片"
          value={BASELINE.fpPerPhoto.toFixed(3)}
          note={`conf ${BASELINE.confThreshold} · margin ${BASELINE.marginThreshold}`}
        />
      </div>

      {/* ---- 2) 每日量（左 3/5）+ 结果构成（右 2/5） ---- */}
      <div className="grid grid-cols-5 gap-4">
        <ChartCard
          title="每日识别照片量（近 14 天）"
          aside={`合计 ${fmt(DAILY.reduce((acc, d) => acc + d.photos, 0))} 张`}
          className="col-span-3"
        >
          <VBars data={DAILY_PHOTOS} unit=" 张" />
        </ChartCard>
        <ChartCard title="识别结果构成" aside="按日堆叠 · 条" className="col-span-2">
          <StackedBars labels={RESULT_LABELS} series={RESULT_SERIES} unit=" 条" />
        </ChartCard>
      </div>

      {/* ---- 3) 级联漏斗（标签含占首段百分比，条右为张数） ---- */}
      <ChartCard
        title="级联漏斗（E0 口径）"
        aside={`首段 ${fmt(FUNNEL_TOTAL)} 张 · 逐级递减`}
      >
        <HBars data={FUNNEL_DATA} unit=" 张" />
      </ChartCard>

      {/* ---- 4) 口径脚注 ---- */}
      <p className="text-xs text-text-secondary">
        bundle {BASELINE.bundle} · 评估集 {BASELINE.evalSet} · 阈值 conf{" "}
        {BASELINE.confThreshold} / margin {BASELINE.marginThreshold} · 样本数据
      </p>
    </div>
  );
}
