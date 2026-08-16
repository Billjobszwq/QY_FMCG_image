import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * 文本输入框。
 *
 * 微交互规范：
 * —— 默认无橙色；hover / focus 切换边框为 accent（accent 仅交互态）
 * —— focus-visible 追加 outline-accent，200ms 颜色过渡
 */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "h-8 w-full rounded-md border border-border bg-background px-2.5 text-sm text-text-primary",
        "placeholder:text-text-secondary/70",
        "transition-colors duration-200 ease-out",
        "hover:border-accent",
        "focus:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
