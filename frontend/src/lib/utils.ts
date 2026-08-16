import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** 合并 Tailwind 类名（shadcn/ui 约定）。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** 将数值限制在 [min, max] 区间内。 */
export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
