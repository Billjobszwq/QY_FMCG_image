import { useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { MotionValue } from "framer-motion";
import { clamp } from "@/lib/utils";

interface ResizeHandleProps {
  minWidth: number;
  minHeight: number;
  /** 当前窗口右/下边缘到桌面右/下边缘的可用空间。 */
  maxWidth: number;
  maxHeight: number;
  width: MotionValue<number>;
  height: MotionValue<number>;
  /** 尺寸变化（拖拽 / 键盘）结束时把最终尺寸提交给窗口管理器。 */
  onCommit: (size: { width: number; height: number }) => void;
}

const KEY_STEP = 16;

/**
 * 窗口右下角缩放手柄。
 * —— 指针：拖拽过程直接写 MotionValue（实时、无渲染滞后），松手才提交 store
 * —— 键盘：可聚焦（Tab），方向键步进 16px（Shift ×4），每次按键即提交
 * 命中区 24×24px（WCAG），视觉抓握纹理仍贴右下角。
 */
export function ResizeHandle({
  minWidth,
  minHeight,
  maxWidth,
  maxHeight,
  width,
  height,
  onCommit,
}: ResizeHandleProps) {
  const start = useRef<{ px: number; py: number; w: number; h: number } | null>(
    null,
  );

  const applySize = (nextWidth: number, nextHeight: number) => {
    width.set(clamp(nextWidth, minWidth, Math.max(minWidth, maxWidth)));
    height.set(clamp(nextHeight, minHeight, Math.max(minHeight, maxHeight)));
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* 合成/非活动指针：退化为元素内跟随 */
    }
    start.current = {
      px: e.clientX,
      py: e.clientY,
      w: width.get(),
      h: height.get(),
    };
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    applySize(
      start.current.w + (e.clientX - start.current.px),
      start.current.h + (e.clientY - start.current.py),
    );
  };

  const finish = () => {
    if (!start.current) return;
    start.current = null;
    onCommit({ width: width.get(), height: height.get() });
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? KEY_STEP * 4 : KEY_STEP;
    let dw = 0;
    let dh = 0;
    switch (e.key) {
      case "ArrowRight":
        dw = step;
        break;
      case "ArrowLeft":
        dw = -step;
        break;
      case "ArrowDown":
        dh = step;
        break;
      case "ArrowUp":
        dh = -step;
        break;
      default:
        return;
    }
    e.preventDefault();
    e.stopPropagation();
    applySize(width.get() + dw, height.get() + dh);
    onCommit({ width: width.get(), height: height.get() });
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="调整窗口大小（方向键步进，Shift 加速）"
      className="absolute right-0 bottom-0 z-10 flex h-6 w-6 cursor-nwse-resize touch-none items-end justify-end p-1 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onKeyDown={onKeyDown}
    >
      {/* 系统风格抓握纹理：三条斜线 */}
      <svg viewBox="0 0 10 10" className="h-2.5 w-2.5 text-border-strong" aria-hidden="true">
        <path
          d="M9 3 L3 9 M9 6 L6 9 M9 9 L9 9"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
