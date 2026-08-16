import { forwardRef } from "react";
import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * 下拉选择：原生 <select> 封装，样式与 Input 一致。
 *
 * —— appearance-none 隐藏系统箭头，chevron 用 monoline SVG（text-secondary）
 * —— hover / focus 边框切 accent（accent 仅交互态），200ms 颜色过渡
 */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          "h-8 w-full appearance-none rounded-md border border-border bg-background px-2.5 pr-8 text-sm text-text-primary",
          "transition-colors duration-200 ease-out",
          "hover:border-accent",
          "focus:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          "disabled:pointer-events-none disabled:opacity-50",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      {/* 下拉箭头（monoline；不拦截指针事件） */}
      <svg
        className="pointer-events-none absolute top-1/2 right-2.5 h-3 w-3 -translate-y-1/2 text-text-secondary"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M2.5 4.5 L6 8 L9.5 4.5"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  ),
);
Select.displayName = "Select";
