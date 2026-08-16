/**
 * StatusBadge：状态徽章（图标 + 文字），全局唯一的状态呈现方式。
 *
 * —— 颜色纪律：仅使用状态保留令牌（success / warning / serious）与
 *    neutral 的次级文本色；禁止挪作系列色 / 静态装饰；
 * —— 无渐变、无毛玻璃；细边框小圆角手工感；
 * —— 文字穿 text-*：徽章本体即“图标 + 文字”，不再嵌套其他文本组件。
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusKind = "good" | "warn" | "serious" | "neutral";

/** 12px 状态图标（16 网格等比缩小，stroke=currentColor）。 */
function KindIcon({ kind }: { kind: StatusKind }) {
  const common = {
    viewBox: "0 0 16 16",
    className: "h-3 w-3 shrink-0",
    "aria-hidden": true as const,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (kind) {
    case "good": // 对勾圆
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.8" />
          <path d="M5.3 8.2 L7.1 10 L10.8 6" />
        </svg>
      );
    case "warn": // 警告三角
      return (
        <svg {...common}>
          <path d="M8 2.6 L14.2 13.2 H1.8 Z" />
          <path d="M8 6.4 V9.2" />
          <circle cx="8" cy="11.2" r="0.7" fill="currentColor" stroke="none" />
        </svg>
      );
    case "serious": // 叉圆
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.8" />
          <path d="M5.8 5.8 L10.2 10.2 M10.2 5.8 L5.8 10.2" />
        </svg>
      );
    case "neutral": // 空心圆点
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.4" />
          <circle cx="8" cy="8" r="1.4" fill="currentColor" stroke="none" />
        </svg>
      );
  }
}

const KIND_CLASSES: Record<StatusKind, string> = {
  good: "text-success border-success/40 bg-success/10",
  warn: "text-warning border-warning/40 bg-warning/10",
  serious: "text-serious border-serious/40 bg-serious/10",
  neutral: "text-text-secondary border-border bg-surface",
};

export function StatusBadge({
  kind,
  children,
  className,
}: {
  kind: StatusKind;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs whitespace-nowrap",
        KIND_CLASSES[kind],
        className,
      )}
    >
      <KindIcon kind={kind} />
      {children}
    </span>
  );
}
