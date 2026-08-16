import { forwardRef } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

/**
 * 按钮（shadcn/ui 风格，底层为 Radix Slot，支持 asChild）。
 *
 * 微交互规范：
 * —— 默认状态无橙色；hover / focus-visible 切换为 accent，0.2s 缓动
 * —— 按下 scale(0.97)，释放回弹
 */
export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  // 近黑底主按钮：悬停时整体切为品牌橙（hover 态允许使用 accent）
  primary:
    "border border-button-bg bg-button-bg text-button-text hover:border-accent hover:bg-accent focus-visible:border-accent focus-visible:bg-accent",
  // 面板色次级按钮：悬停时文字与边框变橙
  secondary:
    "border border-border bg-surface text-text-primary hover:border-accent hover:text-accent focus-visible:border-accent focus-visible:text-accent",
  // 无边框幽灵按钮：悬停时文字变橙
  ghost:
    "border border-transparent bg-transparent text-text-secondary hover:text-accent focus-visible:text-accent",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3 text-[13px]",
  md: "h-9 gap-2 px-4 text-sm",
  lg: "h-11 gap-2 px-5 text-[15px]",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 为 true 时渲染子元素本身（Radix Slot），便于包裹链接等。 */
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant = "primary", size = "md", asChild = false, ...props },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(
          "inline-flex cursor-pointer items-center justify-center rounded-md font-medium whitespace-nowrap select-none",
          "transition-[color,background-color,border-color,transform] duration-200 ease-out",
          "active:scale-[0.97]",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          "disabled:pointer-events-none disabled:opacity-50",
          VARIANT_CLASSES[variant],
          SIZE_CLASSES[size],
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
