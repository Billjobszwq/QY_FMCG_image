/**
 * KV：键值块原语。label 次级小字在左，value 正文在右；
 * 细边框小圆角卡片，行间发丝线分隔，信息密度优先。
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface KVItem {
  label: string;
  value: ReactNode;
}

export function KV({
  items,
  className,
}: {
  items: KVItem[];
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <dl
      className={cn(
        "rounded-md border border-border bg-background px-3",
        className,
      )}
    >
      {items.map((item) => (
        <div
          key={item.label}
          className="grid grid-cols-[minmax(96px,max-content)_1fr] items-baseline gap-x-4 border-b border-border/60 py-1.5 last:border-0"
        >
          <dt className="text-xs text-text-secondary">{item.label}</dt>
          <dd className="min-w-0 break-words text-[13px] text-text-primary">
            {item.value ?? <span className="text-text-secondary">—</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
