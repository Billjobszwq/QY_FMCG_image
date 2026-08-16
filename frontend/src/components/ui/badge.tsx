import { cn } from "@/lib/utils";

/**
 * 趣味标签（Badge）。
 * 使用 Squeak 手写字体令牌 —— 仅用于吉祥物 / 趣味标签等非核心内容。
 */
export function Badge({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-full border border-border bg-surface px-2.5 text-xs text-text-secondary",
        "font-squeak",
        className,
      )}
    >
      {children}
    </span>
  );
}
