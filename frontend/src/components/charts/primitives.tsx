/**
 * 图表原语（纯 SVG 手写，零图表库依赖）。
 *
 * dataviz 规范要点：
 * —— 类目序列色固定顺序 series-1→2→3，sequential 用 ramp-1..5 蓝色渐深；
 *    系列色由调用方以 var(--color-*) 令牌传入，本文件不出现硬编码色值
 * —— 单系列不画图例（标题命名）；≥2 系列图例行置顶
 * —— 网格/轴线用 --color-border 退隐；刻度/标签/图例文字只穿 text 令牌
 * —— 条形细、数据端小圆角、贴基线；hover 层默认提供（命中带 + tooltip）
 * —— 文本不穿系列色；状态色仅 StatusBadge 使用（图标 + 文字）
 */
import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ============================================================================
   共享几何 / 格式化
   ========================================================================== */

/** 竖直条形图统一画布（viewBox 固定，宽度随容器自适应） */
const VB_W = 640;
const VB_H = 200;
const PAD_L = 44;
const PAD_R = 8;
const PAD_T = 10;
const PAD_B = 22;
const PLOT_W = VB_W - PAD_L - PAD_R;
const PLOT_H = VB_H - PAD_T - PAD_B;

/** 向上取整到"好看"的最大刻度（1/2/2.5/5 × 10^k） */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(v));
  const f = v / exp;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nf * exp;
}

/** 刻度文字压缩格式（6000 → 6k，1500 → 1.5k） */
function formatTick(v: number): string {
  if (v >= 10000) return `${Math.round(v / 1000)}k`;
  if (v >= 1000) {
    const s = (v / 1000).toFixed(1);
    return `${s.endsWith(".0") ? s.slice(0, -2) : s}k`;
  }
  return `${Math.round(v * 10) / 10}`;
}

/** tooltip / 直接标签用的千分位数值 */
function formatValue(v: number): string {
  return v.toLocaleString("zh-CN");
}

/** 仅顶部（数据端）圆角、底部贴基线的矩形路径 */
function topRoundedRect(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.max(0, Math.min(r, h, w / 2));
  return [
    `M${x},${y + h}`,
    `L${x},${y + rr}`,
    `Q${x},${y} ${x + rr},${y}`,
    `L${x + w - rr},${y}`,
    `Q${x + w},${y} ${x + w},${y + rr}`,
    `L${x + w},${y + h}`,
    "Z",
  ].join(" ");
}

/** 仅右端（数据端）圆角的横向矩形路径 */
function rightRoundedRect(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.max(0, Math.min(r, w, h / 2));
  return [
    `M${x},${y}`,
    `L${x + w - rr},${y}`,
    `Q${x + w},${y} ${x + w},${y + rr}`,
    `L${x + w},${y + h - rr}`,
    `Q${x + w},${y + h} ${x + w - rr},${y + h}`,
    `L${x},${y + h}`,
    "Z",
  ].join(" ");
}

/** 水平网格线 + 左侧刻度（--color-border 退隐，刻度 text-secondary 10px） */
function GridTicks({ max }: { max: number }) {
  const baseY = PAD_T + PLOT_H;
  return (
    <g>
      {[0.25, 0.5, 0.75, 1].map((f) => {
        const y = PAD_T + PLOT_H * (1 - f);
        return (
          <g key={f}>
            <line x1={PAD_L} x2={VB_W - PAD_R} y1={y} y2={y} stroke="var(--color-border)" strokeWidth="1" />
            <text x={PAD_L - 6} y={y + 3.5} textAnchor="end" fontSize="10" fill="var(--color-text-secondary)">
              {formatTick(max * f)}
            </text>
          </g>
        );
      })}
      {/* 基线 */}
      <line x1={PAD_L} x2={VB_W - PAD_R} y1={baseY} y2={baseY} stroke="var(--color-border)" strokeWidth="1" />
    </g>
  );
}

/** 悬浮提示层：近黑底贴纸式小气泡（位置由调用方按百分比给出） */
function Tooltip({ style, children }: { style: CSSProperties; children: ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute z-10 rounded bg-button-bg px-2 py-1 text-xs leading-relaxed whitespace-nowrap text-button-text"
      style={style}
    >
      {children}
    </div>
  );
}

/** 空数据占位 */
function EmptyPlot({ className }: { className?: string }) {
  return (
    <div className={cn("flex h-24 items-center justify-center text-xs text-text-secondary", className)}>
      暂无数据
    </div>
  );
}

/* ============================================================================
   ChartCard —— 图表卡片容器
   ========================================================================== */

export function ChartCard({
  title,
  aside,
  className,
  children,
}: {
  /** 标题（单系列时标题即系列名，不再画图例） */
  title: string;
  /** 右上角补充说明（右对齐，text-secondary） */
  aside?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("rounded-lg border border-border bg-surface p-4", className)}>
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="font-display text-sm font-bold text-text-primary">{title}</h3>
        {aside !== undefined && <div className="text-right text-xs text-text-secondary">{aside}</div>}
      </header>
      {children}
    </section>
  );
}

/* ============================================================================
   StatTile —— KPI 大数块
   ========================================================================== */

export function StatTile({
  label,
  value,
  note,
  className,
}: {
  /** 指标名 */
  label: string;
  /** 主数值（含单位/符号由调用方拼好） */
  value: ReactNode;
  /** 补充说明（环比/口径） */
  note?: string;
  className?: string;
}) {
  return (
    <div className={cn("rounded-lg border border-border bg-surface px-4 py-3", className)}>
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-1 font-display text-2xl font-bold text-text-primary">{value}</div>
      {note !== undefined && <div className="mt-1 text-xs text-text-secondary">{note}</div>}
    </div>
  );
}

/* ============================================================================
   VBars —— 单系列竖直条形图（无图例，标题即命名）
   ========================================================================== */

export interface VBarDatum {
  label: string;
  value: number;
}

export function VBars({
  data,
  unit = "",
  className,
}: {
  data: VBarDatum[];
  /** 数值单位（如 "张" / "%"），仅出现在 tooltip */
  unit?: string;
  className?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = data.length;
  if (n === 0) return <EmptyPlot className={className} />;

  const max = niceCeil(Math.max(...data.map((d) => d.value), 1));
  const colW = PLOT_W / n;
  const barW = Math.min(26, colW * 0.52); // 条宽适中
  const baseY = PAD_T + PLOT_H;
  const labelSkip = Math.ceil(n / 16); // 列数过多时隔列显示 X 轴标签

  return (
    <div className={cn("relative", className)}>
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="h-auto w-full" role="img" onMouseLeave={() => setHover(null)}>
        <GridTicks max={max} />
        {data.map((d, i) => {
          const h = (d.value / max) * PLOT_H;
          const x = PAD_L + colW * i + (colW - barW) / 2;
          return (
            <path
              key={`bar-${i}`}
              d={topRoundedRect(x, baseY - h, barW, h, 3)}
              fill="var(--color-series-1)"
              opacity={hover === null || hover === i ? 1 : 0.55}
              style={{ transition: "opacity 120ms ease-out" }}
            />
          );
        })}
        {data.map((d, i) =>
          i % labelSkip === 0 ? (
            <text
              key={`label-${i}`}
              x={PAD_L + colW * (i + 0.5)}
              y={VB_H - 6}
              textAnchor="middle"
              fontSize="10"
              fill="var(--color-text-secondary)"
            >
              {d.label}
            </text>
          ) : null,
        )}
        {/* 透明命中带：比条宽，逐列触发 hover；键盘焦点与 hover 等价 */}
        {data.map((d, i) => (
          <rect
            key={`hit-${i}`}
            x={PAD_L + colW * i}
            y={PAD_T}
            width={colW}
            height={PLOT_H}
            fill="transparent"
            tabIndex={0}
            aria-label={`${d.label}：${formatValue(d.value)}${unit}`}
            className="outline-none"
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
          />
        ))}
      </svg>
      {hover !== null && (
        <Tooltip
          style={{
            left: `${((PAD_L + colW * (hover + 0.5)) / VB_W) * 100}%`,
            top: `${((baseY - (data[hover].value / max) * PLOT_H) / VB_H) * 100}%`,
            transform: "translate(-50%, calc(-100% - 6px))",
          }}
        >
          {data[hover].label} · {formatValue(data[hover].value)}
          {unit}
        </Tooltip>
      )}
    </div>
  );
}

/* ============================================================================
   StackedBars —— 堆叠条形图（≥2 系列：顶部图例 + 段间 2px 缝）
   ========================================================================== */

export interface StackedSeries {
  /** 系列名（图例文字） */
  name: string;
  /** 系列色令牌，按契约顺序传入，如 var(--color-series-1) */
  color: string;
  /** 与 labels 等长的数值序列 */
  values: number[];
}

export function StackedBars({
  labels,
  series,
  unit = "",
  className,
}: {
  labels: string[];
  series: StackedSeries[];
  unit?: string;
  className?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = labels.length;
  if (n === 0 || series.length === 0) return <EmptyPlot className={className} />;
  /* 类目序列色只有 3 枚令牌：第 4 系列即诱发硬编码/循环色反模式 */
  if (import.meta.env.DEV && series.length > 3) {
    console.warn("StackedBars：系列数上限 3（类目序列色令牌仅 series-1/2/3），超出请改用小倍图或合并“其他”。");
  }

  const totals = labels.map((_, i) => series.reduce((acc, s) => acc + (s.values[i] ?? 0), 0));
  const max = niceCeil(Math.max(...totals, 1));
  const colW = PLOT_W / n;
  const barW = Math.min(26, colW * 0.52);
  const baseY = PAD_T + PLOT_H;
  const labelSkip = Math.ceil(n / 16);

  return (
    <div className={cn("relative", className)}>
      {/* 顶部图例行：12px 色块 + text-secondary 文字 */}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1.5 text-xs text-text-secondary">
            <span className="inline-block h-3 w-3 rounded-[2px]" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="h-auto w-full" role="img" onMouseLeave={() => setHover(null)}>
        <GridTicks max={max} />
        {labels.map((_, i) => {
          let acc = 0;
          const x = PAD_L + colW * i + (colW - barW) / 2;
          return (
            <g key={`col-${i}`} opacity={hover === null || hover === i ? 1 : 0.55} style={{ transition: "opacity 120ms ease-out" }}>
              {series.map((s) => {
                const v = s.values[i] ?? 0;
                if (v <= 0) return null;
                const h = (v / max) * PLOT_H;
                acc += h;
                return (
                  <rect
                    key={s.name}
                    x={x}
                    y={baseY - acc}
                    width={barW}
                    height={h}
                    fill={s.color}
                    stroke="var(--color-surface)"
                    strokeWidth="2" /* 段间 2px surface 缝 */
                  />
                );
              })}
            </g>
          );
        })}
        {labels.map((label, i) =>
          i % labelSkip === 0 ? (
            <text
              key={`label-${i}`}
              x={PAD_L + colW * (i + 0.5)}
              y={VB_H - 6}
              textAnchor="middle"
              fontSize="10"
              fill="var(--color-text-secondary)"
            >
              {label}
            </text>
          ) : null,
        )}
        {/* 透明命中带：逐列触发 hover；键盘焦点与 hover 等价 */}
        {labels.map((label, i) => (
          <rect
            key={`hit-${i}`}
            x={PAD_L + colW * i}
            y={PAD_T}
            width={colW}
            height={PLOT_H}
            fill="transparent"
            tabIndex={0}
            aria-label={`${label}：合计 ${formatValue(totals[i])}${unit}`}
            className="outline-none"
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
          />
        ))}
      </svg>
      {hover !== null && (
        <Tooltip
          style={{
            left: `${((PAD_L + colW * (hover + 0.5)) / VB_W) * 100}%`,
            top: `${((baseY - (totals[hover] / max) * PLOT_H) / VB_H) * 100}%`,
            transform: "translate(-50%, calc(-100% - 6px))",
          }}
        >
          <div className="font-medium">{labels[hover]}</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
              {s.name} {formatValue(s.values[hover] ?? 0)}
              {unit}
            </div>
          ))}
          <div className="mt-0.5 border-t border-button-text/25 pt-0.5">
            合计 {formatValue(totals[hover])}
            {unit}
          </div>
        </Tooltip>
      )}
    </div>
  );
}

/* ============================================================================
   HBars —— 横向条形图（条右直接标签）
   —— mode="sequential"（默认）：有序类目，sequential 蓝 5 阶按值序取色（如漏斗）
   —— mode="single"：无序（nominal）类目，一律 series-1 同色，
      数值大小只由条长表达（避免 value-ramp-on-nominal 反模式）
   ========================================================================== */

export interface HBarDatum {
  label: string;
  value: number;
}

/** sequential 蓝：深→浅，按值序映射（最大 → ramp-5） */
const RAMP_DARK_TO_LIGHT = [
  "var(--color-ramp-5)",
  "var(--color-ramp-4)",
  "var(--color-ramp-3)",
  "var(--color-ramp-2)",
  "var(--color-ramp-1)",
];

export function HBars({
  data,
  unit = "",
  mode = "sequential",
  className,
}: {
  data: HBarDatum[];
  unit?: string;
  /** sequential=有序类目按值序取色阶；single=无序类目同色 */
  mode?: "sequential" | "single";
  className?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = data.length;
  if (n === 0) return <EmptyPlot className={className} />;

  const LABEL_W = 170; // 左列标签宽度
  const VALUE_W = 64; // 右端数值标签留白
  const ROW_H = 26;
  const BAR_H = 14;
  const PAD_Y = 4;
  const H = PAD_Y * 2 + ROW_H * n;
  const barMax = VB_W - LABEL_W - VALUE_W - 12;
  const max = Math.max(...data.map((d) => d.value), 1);

  // sequential：按值降序排名线性映射 5 档（n>5 时相邻名次不撞色）
  const rankColor = new Map<number, string>();
  if (mode === "sequential") {
    data
      .map((_, i) => i)
      .sort((a, b) => data[b].value - data[a].value)
      .forEach((idx, rank) => {
        const bucket = Math.round((rank * 4) / Math.max(n - 1, 1));
        rankColor.set(idx, RAMP_DARK_TO_LIGHT[bucket]);
      });
  }
  const barColor = (i: number) =>
    mode === "single" ? "var(--color-series-1)" : (rankColor.get(i) ?? "var(--color-ramp-5)");

  return (
    <div className={cn("relative", className)}>
      <svg viewBox={`0 0 ${VB_W} ${H}`} className="h-auto w-full" role="img" onMouseLeave={() => setHover(null)}>
        {data.map((d, i) => {
          const rowY = PAD_Y + ROW_H * i;
          const barY = rowY + (ROW_H - BAR_H) / 2;
          const w = Math.max(2, (d.value / max) * barMax);
          return (
            <g key={`row-${i}`}>
              {/* hover 行底色（退隐的 border 色） */}
              {hover === i && (
                <rect x={2} y={rowY} width={VB_W - 4} height={ROW_H} rx={4} fill="var(--color-border)" opacity={0.4} />
              )}
              {/* 左列标签：左对齐 text-secondary，不穿系列色 */}
              <text x={6} y={rowY + ROW_H / 2 + 3.5} textAnchor="start" fontSize="11" fill="var(--color-text-secondary)">
                {d.label}
              </text>
              {/* 条：右端 3px 圆角；颜色由 mode 决定 */}
              <path d={rightRoundedRect(LABEL_W, barY, w, BAR_H, 3)} fill={barColor(i)} />
              {/* 条右直接标签：数值 text-primary */}
              <text
                x={LABEL_W + w + 6}
                y={rowY + ROW_H / 2 + 3.5}
                textAnchor="start"
                fontSize="11"
                fontWeight={600}
                fill="var(--color-text-primary)"
              >
                {formatValue(d.value)}
                {unit}
              </text>
              {/* 整行命中带 */}
              <rect
                x={0}
                y={rowY}
                width={VB_W}
                height={ROW_H}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <Tooltip
          style={{
            left: `${(LABEL_W / VB_W) * 100}%`,
            top: `${((PAD_Y + ROW_H * hover) / H) * 100}%`,
            transform: "translate(0, calc(-100% - 2px))",
          }}
        >
          {data[hover].label} · {formatValue(data[hover].value)}
          {unit}
        </Tooltip>
      )}
    </div>
  );
}

/* ============================================================================
   StatusBadge —— 状态徽章（状态保留色专用：永远图标 + 文字）
   ========================================================================== */

export type StatusTone = "good" | "warn" | "serious" | "muted";

/** tone → 状态令牌（muted 退到次级文本色） */
const TONE_TOKEN: Record<StatusTone, string> = {
  good: "var(--color-success)",
  warn: "var(--color-warning)",
  serious: "var(--color-serious)",
  muted: "var(--color-text-secondary)",
};

/** 6px 几何小图标（monoline，currentColor）：圆点 / 三角 / 叉 / 横线 */
function ToneIcon({ tone }: { tone: StatusTone }) {
  switch (tone) {
    case "good":
      return (
        <svg width="6" height="6" viewBox="0 0 6 6" aria-hidden="true">
          <circle cx="3" cy="3" r="2.5" fill="currentColor" />
        </svg>
      );
    case "warn":
      return (
        <svg width="6" height="6" viewBox="0 0 6 6" aria-hidden="true">
          <path d="M3 0.6 L5.6 5.4 L0.4 5.4 Z" fill="currentColor" />
        </svg>
      );
    case "serious":
      return (
        <svg width="6" height="6" viewBox="0 0 6 6" aria-hidden="true">
          <path d="M1 1 L5 5 M5 1 L1 5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      );
    case "muted":
      return (
        <svg width="6" height="6" viewBox="0 0 6 6" aria-hidden="true">
          <rect x="0.5" y="2.4" width="5" height="1.2" rx="0.6" fill="currentColor" />
        </svg>
      );
  }
}

export function StatusBadge({
  tone,
  children,
  className,
}: {
  tone: StatusTone;
  /** 状态文字（必须与图标同时出现，不用颜色单独表意） */
  children: ReactNode;
  className?: string;
}) {
  const token = TONE_TOKEN[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      )}
      style={{
        color: token,
        /* 浅色底：令牌色 12% 混入面板色；细边框 28% —— 均走令牌，无硬编码 */
        backgroundColor: `color-mix(in srgb, ${token} 12%, var(--color-surface))`,
        border: `1px solid color-mix(in srgb, ${token} 28%, var(--color-surface))`,
      }}
    >
      <ToneIcon tone={tone} />
      {children}
    </span>
  );
}
