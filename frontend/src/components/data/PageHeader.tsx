/**
 * PageHeader：页面头原语。左侧标题（display 字体）+ 描述（次级小字），
 * 右侧 aside 放页面级操作（按钮 / 筛选）。
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  desc,
  aside,
  className,
}: {
  title: string;
  desc?: string;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex items-start justify-between gap-3",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="font-display text-lg font-bold text-text-primary">
          {title}
        </h1>
        {desc && (
          <p className="mt-0.5 text-[13px] text-text-secondary">{desc}</p>
        )}
      </div>
      {aside && <div className="flex shrink-0 items-center gap-2">{aside}</div>}
    </header>
  );
}
