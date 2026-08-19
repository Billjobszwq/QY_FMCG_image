import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import type { ReactNode } from "react";
import { clamp } from "@/lib/utils";

/* ============================================================================
   全局窗口管理器（Window Manager）
   —— 维护所有窗口的 id / position / size / isMinimized / isMaximized / zIndex
   —— 提供 openWindow / closeWindow / minimizeWindow / maximizeWindow(toggle)
      / bringToFront 等方法
   —— v5：整桌排列操作 cascadeWindows / tileWindows / minimizeAll /
      closeAllWindows（菜单栏「窗口」菜单消费）
   ========================================================================== */

/** 底部任务栏高度（与 --taskbar-height 令牌保持一致）。 */
export const TASKBAR_HEIGHT = 48;
/** 窗口标题栏高度（与 --titlebar-height 令牌保持一致）。 */
export const TITLEBAR_HEIGHT = 40;

/** 登录窗口 id（桌面壳与 closeAllWindows 共用：关全部时保留）。 */
export const LOGIN_WINDOW_ID = "login";

const DEFAULT_MIN_WIDTH = 320;
const DEFAULT_MIN_HEIGHT = 200;

/** 层叠重排：起点与步长（每个窗口向右下各错一格）。 */
const CASCADE_ORIGIN = { x: 40, y: 40 };
const CASCADE_STEP = 28;

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface WindowRect extends Point, Size {}

/** 打开一个窗口所需的完整描述。 */
export interface WindowDescriptor {
  /** 唯一标识；重复 openWindow(id) 是幂等的（保留位置、置前）。 */
  id: string;
  title: string;
  /** 窗口内容（占位阶段可传任意 React 节点，后续替换为真实页面组件）。 */
  content: ReactNode;
  /** 任务栏 / 桌面图标处显示的简单 SVG 图标（可选）。 */
  icon?: ReactNode;
  defaultPosition: Point;
  defaultSize: Size;
  minWidth?: number;
  minHeight?: number;
  /** 是否允许右下角拖拽调整大小（默认 true）。 */
  resizable?: boolean;
  /** 是否显示关闭按钮（默认 true）。 */
  closable?: boolean;
}

/** 窗口在管理器中的运行时状态。 */
export interface WindowState extends WindowDescriptor {
  minWidth: number;
  minHeight: number;
  resizable: boolean;
  closable: boolean;
  position: Point;
  size: Size;
  isMinimized: boolean;
  isMaximized: boolean;
  zIndex: number;
  /** 最大化前的位置/尺寸，用于还原。 */
  restoreRect: WindowRect | null;
}

interface WindowManagerState {
  windows: Record<string, WindowState>;
  /** 打开顺序（任务栏按此顺序展示）。 */
  order: string[];
  /** 当前聚焦窗口 id；Esc 等场景下可为 null。 */
  activeId: string | null;
  /** 单调递增的 z-index 计数器。 */
  zTop: number;

  openWindow: (descriptor: WindowDescriptor) => void;
  closeWindow: (id: string, force?: boolean) => void;
  minimizeWindow: (id: string) => void;
  /** 从最小化恢复并聚焦。 */
  restoreWindow: (id: string) => void;
  /** 最大化 / 还原 切换。 */
  toggleMaximize: (id: string) => void;
  bringToFront: (id: string) => void;
  setActive: (id: string | null) => void;
  /** 拖拽结束后提交位置（拖拽过程中走 MotionValue，避免逐帧渲染）。 */
  commitPosition: (id: string, position: Point) => void;
  /** 调整大小结束后提交尺寸。 */
  commitSize: (id: string, size: Size) => void;
  /** 视口变化时让最大化窗口跟随新尺寸。 */
  syncMaximizedSizes: () => void;
  /** v5：打开的窗口按 28px 层叠重排，从 (40,40) 起；最大化还原、最小化带回。 */
  cascadeWindows: () => void;
  /** v5：网格平铺（视口宽 × 视口高-任务栏），1 窗独占、≥2 窗两列自适应。 */
  tileWindows: () => void;
  /** v5：最小化全部窗口并清除聚焦。 */
  minimizeAll: () => void;
  /** v5：关闭全部窗口（登录窗除外）。 */
  closeAllWindows: () => void;
}

function resolveDescriptor(d: WindowDescriptor) {
  return {
    minWidth: d.minWidth ?? DEFAULT_MIN_WIDTH,
    minHeight: d.minHeight ?? DEFAULT_MIN_HEIGHT,
    resizable: d.resizable ?? true,
    closable: d.closable ?? true,
  };
}

/** 首次打开时把默认位置夹进视口，避免小屏下窗口开到屏幕外。 */
function clampDefaultPosition(d: WindowDescriptor) {
  const vw = window.innerWidth;
  const vh = window.innerHeight - TASKBAR_HEIGHT;
  return {
    x: clamp(d.defaultPosition.x, 8, Math.max(8, vw - d.defaultSize.width - 8)),
    y: clamp(d.defaultPosition.y, 8, Math.max(8, vh - d.defaultSize.height - 8)),
  };
}

export const useWindowManager = create<WindowManagerState>()((set) => ({
  windows: {},
  order: [],
  activeId: null,
  zTop: 10,

  openWindow: (d) =>
    set((s) => {
      const existing = s.windows[d.id];
      const zTop = s.zTop + 1;
      // 幂等：窗口已存在时保留其位置 / 尺寸，仅更新内容并置前。
      const geometry = existing
        ? {
            position: existing.position,
            size: existing.size,
            isMaximized: existing.isMaximized,
            restoreRect: existing.restoreRect,
          }
        : {
            position: clampDefaultPosition(d),
            size: { ...d.defaultSize },
            isMaximized: false,
            restoreRect: null,
          };
      return {
        zTop,
        windows: {
          ...s.windows,
          [d.id]: {
            ...d,
            ...resolveDescriptor(d),
            ...geometry,
            isMinimized: false,
            zIndex: zTop,
          },
        },
        order: existing ? s.order : [...s.order, d.id],
        activeId: d.id,
      };
    }),

  closeWindow: (id, force = false) =>
    set((s) => {
      if (!s.windows[id]) return {};
      /* closable=false 的窗口（登录窗）拒绝用户/快捷键关闭；
         壳层程序性关闭（登录成功/登出）显式传 force */
      if (!force && s.windows[id].closable === false) return {};
      const windows = { ...s.windows };
      delete windows[id];
      return {
        windows,
        order: s.order.filter((w) => w !== id),
        activeId: s.activeId === id ? null : s.activeId,
      };
    }),

  minimizeWindow: (id) =>
    set((s) => {
      const w = s.windows[id];
      if (!w) return {};
      return {
        windows: { ...s.windows, [id]: { ...w, isMinimized: true } },
        activeId: s.activeId === id ? null : s.activeId,
      };
    }),

  restoreWindow: (id) =>
    set((s) => {
      const w = s.windows[id];
      if (!w) return {};
      const zTop = s.zTop + 1;
      return {
        zTop,
        windows: { ...s.windows, [id]: { ...w, isMinimized: false, zIndex: zTop } },
        activeId: id,
      };
    }),

  toggleMaximize: (id) =>
    set((s) => {
      const w = s.windows[id];
      if (!w) return {};
      if (w.isMaximized && w.restoreRect) {
        return {
          activeId: id,
          windows: {
            ...s.windows,
            [id]: {
              ...w,
              isMaximized: false,
              position: { x: w.restoreRect.x, y: w.restoreRect.y },
              size: { width: w.restoreRect.width, height: w.restoreRect.height },
              restoreRect: null,
            },
          },
        };
      }
      return {
        activeId: id,
        windows: {
          ...s.windows,
          [id]: {
            ...w,
            isMaximized: true,
            restoreRect: {
              x: w.position.x,
              y: w.position.y,
              width: w.size.width,
              height: w.size.height,
            },
            position: { x: 0, y: 0 },
            size: {
              width: window.innerWidth,
              height: window.innerHeight - TASKBAR_HEIGHT,
            },
          },
        },
      };
    }),

  bringToFront: (id) =>
    set((s) => {
      const w = s.windows[id];
      if (!w) return {};
      if (w.zIndex === s.zTop) return { activeId: id };
      const zTop = s.zTop + 1;
      return {
        zTop,
        activeId: id,
        windows: { ...s.windows, [id]: { ...w, zIndex: zTop } },
      };
    }),

  setActive: (id) => set({ activeId: id }),

  commitPosition: (id, position) =>
    set((s) =>
      s.windows[id]
        ? { windows: { ...s.windows, [id]: { ...s.windows[id], position } } }
        : {},
    ),

  commitSize: (id, size) =>
    set((s) =>
      s.windows[id]
        ? { windows: { ...s.windows, [id]: { ...s.windows[id], size } } }
        : {},
    ),

  syncMaximizedSizes: () =>
    set((s) => {
      const width = window.innerWidth;
      const height = window.innerHeight - TASKBAR_HEIGHT;
      const windows = { ...s.windows };
      let changed = false;
      for (const [id, w] of Object.entries(windows)) {
        if (w.isMaximized) {
          windows[id] = { ...w, size: { width, height } };
          changed = true;
        }
      }
      return changed ? { windows } : {};
    }),

  cascadeWindows: () =>
    set((s) => {
      const ids = s.order.filter((id) => s.windows[id]);
      if (ids.length === 0) return {};
      const windows = { ...s.windows };
      ids.forEach((id, i) => {
        const w = windows[id];
        // 最大化窗口先还原到记忆尺寸再参与层叠（restoreRect 缺失时保留现尺寸）。
        const size =
          w.isMaximized && w.restoreRect
            ? { width: w.restoreRect.width, height: w.restoreRect.height }
            : w.size;
        windows[id] = {
          ...w,
          isMinimized: false,
          isMaximized: false,
          restoreRect: null,
          size,
          position: {
            x: CASCADE_ORIGIN.x + i * CASCADE_STEP,
            y: CASCADE_ORIGIN.y + i * CASCADE_STEP,
          },
        };
      });
      return { windows };
    }),

  tileWindows: () =>
    set((s) => {
      const ids = s.order.filter((id) => s.windows[id]);
      const n = ids.length;
      if (n === 0) return {};
      // 平铺可用区 = 视口宽 × (视口高 - 任务栏)，与最大化口径一致。
      const availW = window.innerWidth;
      const availH = window.innerHeight - TASKBAR_HEIGHT;
      const cols = n === 1 ? 1 : 2;
      const rows = Math.ceil(n / cols);
      const cellW = Math.floor(availW / cols);
      const cellH = Math.floor(availH / rows);
      const windows = { ...s.windows };
      ids.forEach((id, i) => {
        const w = windows[id];
        windows[id] = {
          ...w,
          isMinimized: false,
          isMaximized: false,
          restoreRect: null,
          position: {
            x: (i % cols) * cellW,
            y: Math.floor(i / cols) * cellH,
          },
          size: { width: cellW, height: cellH },
        };
      });
      return { windows };
    }),

  minimizeAll: () =>
    set((s) => {
      if (s.order.length === 0) return {};
      const windows = { ...s.windows };
      for (const id of s.order) {
        const w = windows[id];
        if (w && !w.isMinimized) windows[id] = { ...w, isMinimized: true };
      }
      return { windows, activeId: null };
    }),

  closeAllWindows: () =>
    set((s) => {
      const closable = s.order.filter(
        (id) => id !== LOGIN_WINDOW_ID && s.windows[id],
      );
      if (closable.length === 0) return {};
      const windows = { ...s.windows };
      for (const id of closable) delete windows[id];
      return {
        windows,
        order: s.order.filter((id) => windows[id]),
        activeId: s.activeId && windows[s.activeId] ? s.activeId : null,
      };
    }),
}));

/** 按打开顺序返回所有窗口（任务栏 / 桌面渲染用）。 */
export function useOrderedWindows(): WindowState[] {
  return useWindowManager(
    useShallow((s) => s.order.map((id) => s.windows[id]).filter(Boolean)),
  );
}

/** 读取单个窗口状态。 */
export function useWindow(id: string): WindowState | undefined {
  return useWindowManager((s) => s.windows[id]);
}

/** 当前聚焦的窗口 id（快捷键等场景）。 */
export function useActiveWindowId(): string | null {
  return useWindowManager((s) => s.activeId);
}

/** 供非 React 上下文（如全局快捷键）直接取用方法。 */
export function getWindowManager() {
  return useWindowManager.getState();
}
