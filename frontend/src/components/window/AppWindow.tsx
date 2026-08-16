import { useEffect } from "react";
import {
  animate,
  motion,
  useDragControls,
  useMotionValue,
  useReducedMotion,
} from "framer-motion";
import { clamp, cn } from "@/lib/utils";
import {
  TITLEBAR_HEIGHT,
  useWindowManager,
  type WindowState,
} from "@/store/windowStore";
import { useDesktopSize } from "@/hooks/useDesktopSize";
import { TitleBar } from "./TitleBar";
import { ResizeHandle } from "./ResizeHandle";

/**
 * AppWindow —— 窗口系统的核心渲染组件。
 *
 * 行为：
 * —— 拖拽标题栏移动（Framer Motion dragControls，实时无滞后）
 * —— 右下角拖拽调整大小（直接写 MotionValue，松手提交 store）
 * —— 点击窗口任意处置于最顶层（z-index 管理）
 * —— 双击标题栏最大化 / 还原
 * —— 关闭（×）/ 最小化（—）/ 最大化（□）按钮
 * —— 最小化时缩向任务栏（保留在 DOM 中，透明度 0 + pointer-events 关闭）
 * —— 打开动画：scale 0.95 → 1 + 淡入，200ms ease-out
 * —— 内容滚动限定在窗口内部
 *
 * 属性（由 WindowDescriptor 提供，见 store/windowStore.ts）：
 *   title / defaultPosition / defaultSize / minWidth / minHeight /
 *   resizable(默认 true) / closable(默认 true)
 */
export function AppWindow({ win }: { win: WindowState }) {
  const desktop = useDesktopSize();
  const isActive = useWindowManager((s) => s.activeId === win.id);
  const dragControls = useDragControls();
  /* 命令式 animate() 不消费 MotionConfig 上下文，需手动尊重减弱动态效果偏好 */
  const prefersReducedMotion = useReducedMotion();

  /* 位置 / 尺寸用 MotionValue 驱动：拖拽与缩放过程零渲染开销 */
  const x = useMotionValue(win.position.x);
  const y = useMotionValue(win.position.y);
  const width = useMotionValue(win.size.width);
  const height = useMotionValue(win.size.height);

  /* 程序性变更（最大化 / 还原 / 重新打开）时同步 MotionValue，带 200ms 动画 */
  useEffect(() => {
    const opts = {
      duration: prefersReducedMotion ? 0 : 0.2,
      ease: "easeOut" as const,
    };
    const animations = [
      animate(x, win.position.x, opts),
      animate(y, win.position.y, opts),
      animate(width, win.size.width, opts),
      animate(height, win.size.height, opts),
    ];
    return () => animations.forEach((a) => a.stop());
  }, [win.position.x, win.position.y, win.size.width, win.size.height, prefersReducedMotion, x, y, width, height]);

  const {
    commitPosition,
    commitSize,
    bringToFront,
    minimizeWindow,
    toggleMaximize,
    closeWindow,
  } = useWindowManager.getState();

  /* 拖拽约束：允许部分移出屏幕，但标题栏始终可触达（越界时橡皮筋回弹） */
  const constraints = {
    left: -(win.size.width - 80),
    right: Math.max(desktop.width - 80, 0),
    top: 0,
    bottom: Math.max(desktop.height - TITLEBAR_HEIGHT - 8, 0),
  };

  const handleDragEnd = () => {
    commitPosition(win.id, {
      x: clamp(x.get(), constraints.left, constraints.right),
      y: clamp(y.get(), constraints.top, constraints.bottom),
    });
  };

  /* 最小化时向任务栏方向收缩 */
  const minimizePull = Math.max(
    desktop.height - (win.position.y + win.size.height),
    48,
  );

  return (
    <motion.div
      /* 语义：每个窗口即一个对话框，无障碍名取窗口标题 */
      role="dialog"
      aria-label={win.title}
      className={cn(
        "pointer-events-auto absolute top-0 left-0",
        /* 最小化后外壳不再隐形遮挡桌面（命中交还图标层） */
        win.isMinimized && "pointer-events-none",
      )}
      style={{ x, y, width, height, zIndex: win.zIndex }}
      drag={!win.isMaximized}
      dragControls={dragControls}
      dragListener={false}
      dragMomentum={false}
      dragElastic={0.12}
      dragConstraints={win.isMaximized ? undefined : constraints}
      onDragEnd={handleDragEnd}
      /* 点击窗口任意处置前（capture 阶段先于子元素 stopPropagation） */
      onPointerDownCapture={() => bringToFront(win.id)}
      exit={{ scale: 0.96, opacity: 0 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
    >
      {/* 内层负责打开 / 最小化 / 关闭的缩放与淡入动画 */}
      <motion.div
        className={cn(
          "relative flex h-full w-full flex-col overflow-hidden border bg-surface transition-colors duration-200",
          isActive
            ? "border-border-strong shadow-window-active"
            : "border-border shadow-window",
          win.isMinimized && "pointer-events-none",
        )}
        style={{
          borderRadius: "var(--window-radius)",
          transformOrigin: "50% 100%",
        }}
        initial={{ scale: 0.95, opacity: 0 }}
        animate={
          win.isMinimized
            ? { scale: 0.05, opacity: 0, y: minimizePull }
            : { scale: 1, opacity: 1, y: 0 }
        }
        transition={{ duration: 0.2, ease: "easeOut" }}
        aria-hidden={win.isMinimized || undefined}
        inert={win.isMinimized}
      >
        <TitleBar
          win={win}
          isActive={isActive}
          onStartDrag={
            win.isMaximized ? undefined : (e) => dragControls.start(e)
          }
          onMinimize={() => minimizeWindow(win.id)}
          onToggleMaximize={() => toggleMaximize(win.id)}
          onClose={() => closeWindow(win.id)}
        />

        {/* 内容区：滚动限定在窗口内部 */}
        <div className="min-h-0 flex-1 overflow-auto bg-background">
          {win.content}
        </div>

        {win.resizable && !win.isMaximized && !win.isMinimized && (
          <ResizeHandle
            minWidth={win.minWidth}
            minHeight={win.minHeight}
            maxWidth={desktop.width - win.position.x}
            maxHeight={desktop.height - win.position.y}
            width={width}
            height={height}
            onCommit={(size) => commitSize(win.id, size)}
          />
        )}
      </motion.div>
    </motion.div>
  );
}
