/**
 * 标注审核页（窗口内容组件，不含窗口壳）。
 *
 * 布局：头部口径说明 + 原因过滤 → 队列卡片列表。
 * 每张卡片：左侧货架占位草图 + 候选框叠加层，右侧 SKU 信息、进审理由与操作。
 *
 * 设计红线：
 * —— 颜色/字体一律令牌（series-1 仅用于候选框这一"选中/标注"语义）
 * —— 状态色只通过 StatusBadge（图标+文字）出现
 * —— 无渐变、无毛玻璃；细边框、小圆角、monoline 手绘感
 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { StatusBadge, type StatusTone } from "@/components/charts/primitives";
import { BASELINE, REVIEW_QUEUE, type ReviewItemSample } from "@/data/sample";

/* ============================================================================
   进审理由归类（样本数据 reason 为自由文案，此处归到三类口径）
   ========================================================================== */

type ReasonKind = "low-margin" | "unknown" | "hardcase";

/** 归类 → 中文标签 */
const REASON_LABEL: Record<ReasonKind, string> = {
  "low-margin": "边距不足",
  unknown: "未知 SKU",
  hardcase: "硬案例",
};

/** 归类 → 状态徽章 tone（low-margin=warn / unknown=serious / hardcase=muted） */
const REASON_TONE: Record<ReasonKind, StatusTone> = {
  "low-margin": "warn",
  unknown: "serious",
  hardcase: "muted",
};

/** 从样本 reason 文案归类：margin → 边距不足；unknown → 未知 SKU；其余（conf 偏低等）→ 硬案例 */
function classifyReason(reason: string): ReasonKind {
  if (reason.includes("margin")) return "low-margin";
  if (reason.includes("unknown")) return "unknown";
  return "hardcase";
}

/** 过滤选项（全部 + 三类理由） */
const REASON_FILTERS: { value: "all" | ReasonKind; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "low-margin", label: "边距不足" },
  { value: "unknown", label: "未知 SKU" },
  { value: "hardcase", label: "硬案例" },
];

/* ============================================================================
   候选框占位坐标（220×140 货架占位图的百分比坐标）
   —— 样本数据未含检测框，按审核单号固定映射，仅用于演示叠加层
   ========================================================================== */

interface BoxRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const PLACEHOLDER_BOX: Record<string, BoxRect> = {
  // 上层最左的罐
  "RV-20260815-014": { x: 7.3, y: 21.4, w: 13.6, h: 27.1 },
  // 下层中部的瓶
  "RV-20260815-009": { x: 28.2, y: 60, w: 11.8, h: 34.3 },
  // 上层右侧的宽罐
  "RV-20260815-003": { x: 53.6, y: 25.7, w: 15.5, h: 22.9 },
};

/** 未命中映射时的兜底框（画面中部） */
const FALLBACK_BOX: BoxRect = { x: 40, y: 28, w: 16, h: 26 };

/* ============================================================================
   货架占位草图（monoline：两层隔板 + 7 个瓶/罐，无填充无渐变）
   ========================================================================== */

function ShelfSketch() {
  return (
    <svg viewBox="0 0 220 140" className="h-auto w-full" aria-hidden="true">
      <g
        fill="none"
        stroke="var(--color-text-secondary)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* 两层隔板横线 + 端头小支撑 */}
        <path d="M10 64 H210" />
        <path d="M10 128 H210" />
        <path d="M12 64 v5 M208 64 v5 M12 128 v5 M208 128 v5" strokeWidth="1" opacity="0.7" />
        {/* 上层：罐 / 瓶（瓶颈+瓶身）/ 高罐 / 宽罐 */}
        <rect x="20" y="34" width="22" height="30" rx="3" />
        <rect x="59" y="26" width="6" height="9" rx="2" />
        <rect x="53" y="34" width="18" height="30" rx="3" />
        <rect x="86" y="26" width="20" height="38" rx="3" />
        <rect x="122" y="40" width="26" height="24" rx="4" />
        {/* 下层：罐 / 瓶（瓶颈+瓶身）/ 罐 */}
        <rect x="26" y="98" width="22" height="30" rx="3" />
        <rect x="72" y="88" width="6" height="9" rx="2" />
        <rect x="66" y="96" width="18" height="32" rx="3" />
        <rect x="106" y="102" width="20" height="26" rx="3" />
      </g>
    </svg>
  );
}

/* ============================================================================
   候选框叠加层（series-1 描边 + 四角拟物手柄 + 框上小标签）
   ========================================================================== */

function CandidateBox({ box, label, conf }: { box: BoxRect; label: string; conf: number }) {
  return (
    <div
      className="pointer-events-none absolute border-2 border-series-1"
      style={{ left: `${box.x}%`, top: `${box.y}%`, width: `${box.w}%`, height: `${box.h}%` }}
    >
      {/* 框上小标签：候选名 + 置信度（近黑贴纸） */}
      <span className="absolute -top-5 left-0 max-w-[150px] truncate rounded bg-button-bg px-1 text-[10px] leading-4 text-button-text whitespace-nowrap">
        {label} · {Math.round(conf * 100)}%
      </span>
      {/* 四角小方块拟物手柄 */}
      <span className="absolute -top-1 -left-1 h-[7px] w-[7px] rounded-[2px] border border-series-1 bg-surface" />
      <span className="absolute -top-1 -right-1 h-[7px] w-[7px] rounded-[2px] border border-series-1 bg-surface" />
      <span className="absolute -bottom-1 -left-1 h-[7px] w-[7px] rounded-[2px] border border-series-1 bg-surface" />
      <span className="absolute -right-1 -bottom-1 h-[7px] w-[7px] rounded-[2px] border border-series-1 bg-surface" />
    </div>
  );
}

/* ============================================================================
   单条审核卡片
   ========================================================================== */

/** 单卡决策状态：未处理 / 已接受 / 已送改正 */
type Decision = "accepted" | "rework";

function ReviewCard({
  item,
  decision,
  onDecide,
}: {
  item: ReviewItemSample;
  decision: Decision | undefined;
  onDecide: (id: string, decision: Decision) => void;
}) {
  const kind = classifyReason(item.reason);
  const box = PLACEHOLDER_BOX[item.id] ?? FALLBACK_BOX;

  return (
    <article className="grid grid-cols-[220px_1fr] gap-4 rounded-lg border border-border bg-surface p-3 transition-colors duration-200 hover:border-border-strong">
      {/* 左：货架占位草图 + 候选框叠加 */}
      <div className="relative w-[220px]">
        <ShelfSketch />
        <CandidateBox box={box} label={item.candidate} conf={item.conf} />
      </div>

      {/* 右：SKU 信息 / 理由 / 操作 */}
      <div className="flex min-w-0 flex-col gap-2">
        {/* SKU 名称 + 审核单号 */}
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <h3 className="font-display text-sm font-bold text-text-primary">{item.candidate}</h3>
          <span className="font-mono text-xs text-text-secondary">{item.id}</span>
        </div>

        {/* 理由徽章 + 置信度/间距直接标签 */}
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={REASON_TONE[kind]}>{REASON_LABEL[kind]}</StatusBadge>
          <span className="text-xs text-text-secondary">
            置信度 {Math.round(item.conf * 100)}% · 间距 {item.margin.toFixed(2)} ·{" "}
            {item.reason}
          </span>
        </div>

        {/* 来源元信息：点位 / 照片 / 到达时间 */}
        <div className="text-xs text-text-secondary">
          {item.shelf} · {item.photoId} · 到达 {item.arrivedAt}
        </div>

        {/* 操作行：接受 / 送改正；决策后切换为状态徽章（state per card） */}
        <div className="mt-auto flex items-center gap-2 pt-1">
          {decision === "accepted" ? (
            <StatusBadge tone="good">已接受</StatusBadge>
          ) : decision === "rework" ? (
            <StatusBadge tone="muted">已送改正</StatusBadge>
          ) : (
            <>
              <Button size="sm" variant="primary" onClick={() => onDecide(item.id, "accepted")}>
                接受
              </Button>
              <Button size="sm" variant="secondary" onClick={() => onDecide(item.id, "rework")}>
                送改正
              </Button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

/* ============================================================================
   页面主体
   ========================================================================== */

export default function ReviewContent() {
  /** 原因过滤（默认全部） */
  const [filter, setFilter] = useState<"all" | ReasonKind>("all");
  /** 逐卡决策状态 */
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});

  const visible =
    filter === "all" ? REVIEW_QUEUE : REVIEW_QUEUE.filter((it) => classifyReason(it.reason) === filter);

  const handleDecide = (id: string, decision: Decision) => {
    setDecisions((prev) => ({ ...prev, [id]: decision }));
  };

  return (
    <div className="space-y-4 p-5">
      {/* 头部行：E0 口径说明 + 原因过滤 */}
      <header className="flex items-center justify-between gap-3">
        <p className="text-sm text-text-secondary">
          E0 口径：已匹配中 {BASELINE.reviewRatioPct}% 进入 review · 样本队列 {REVIEW_QUEUE.length} 条
        </p>
        <Select
          aria-label="原因过滤"
          className="w-36 shrink-0"
          value={filter}
          onChange={(e) => setFilter(e.target.value as "all" | ReasonKind)}
        >
          {REASON_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
      </header>

      {/* 队列卡片列表 */}
      {visible.length > 0 ? (
        <div className="space-y-3">
          {visible.map((item) => (
            <ReviewCard
              key={item.id}
              item={item}
              decision={decisions[item.id]}
              onDecide={handleDecide}
            />
          ))}
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center rounded-lg border border-border bg-surface text-xs text-text-secondary">
          当前筛选下暂无待审条目
        </div>
      )}
    </div>
  );
}
