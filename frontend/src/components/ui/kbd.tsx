import { cn } from "@/lib/utils";

/** 键盘按键样式（快捷键说明用）。 */
export function Kbd({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <kbd
      className={cn(
        "inline-flex h-6 min-w-6 items-center justify-center rounded-md border border-border border-b-2 bg-surface px-1.5 font-mono text-[11px] text-text-secondary",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
