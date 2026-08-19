import { beforeEach, describe, expect, it } from "vitest";
import {
  TASKBAR_HEIGHT,
  useWindowManager,
  type WindowDescriptor,
} from "./windowStore";

function descriptor(over: Partial<WindowDescriptor> = {}): WindowDescriptor {
  return {
    id: "w1",
    title: "窗口一",
    content: null,
    defaultPosition: { x: 100, y: 100 },
    defaultSize: { width: 400, height: 300 },
    ...over,
  };
}

beforeEach(() => {
  useWindowManager.setState({
    windows: {},
    order: [],
    activeId: null,
    zTop: 10,
  });
});

describe("openWindow", () => {
  it("按默认几何创建窗口并聚焦", () => {
    useWindowManager.getState().openWindow(descriptor());
    const { windows, order, activeId } = useWindowManager.getState();
    expect(order).toEqual(["w1"]);
    expect(activeId).toBe("w1");
    expect(windows.w1.position).toEqual({ x: 100, y: 100 });
    expect(windows.w1.size).toEqual({ width: 400, height: 300 });
    expect(windows.w1.resizable).toBe(true);
    expect(windows.w1.closable).toBe(true);
  });

  it("同 id 重复调用幂等：保留位置、不重复入序、仅置前", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().commitPosition("w1", { x: 222, y: 111 });
    s().openWindow(descriptor({ defaultPosition: { x: 0, y: 0 } }));
    expect(s().order).toEqual(["w1"]);
    expect(s().windows.w1.position).toEqual({ x: 222, y: 111 });
  });

  it("小屏下默认位置夹进视口", () => {
    useWindowManager.getState().openWindow(descriptor({ defaultPosition: { x: 99999, y: 99999 } }));
    const w = useWindowManager.getState().windows.w1;
    expect(w.position.x).toBe(window.innerWidth - 400 - 8);
    expect(w.position.y).toBeLessThanOrEqual(window.innerHeight - TASKBAR_HEIGHT - 300 - 8);
  });
});

describe("closeWindow", () => {
  it("移除窗口并清理 activeId", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().closeWindow("w1");
    expect(s().windows.w1).toBeUndefined();
    expect(s().order).toEqual([]);
    expect(s().activeId).toBeNull();
  });
});

describe("minimize / restore", () => {
  it("最小化清除聚焦，restore 恢复并置前", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().minimizeWindow("w1");
    expect(s().windows.w1.isMinimized).toBe(true);
    expect(s().activeId).toBeNull();
    s().restoreWindow("w1");
    expect(s().windows.w1.isMinimized).toBe(false);
    expect(s().activeId).toBe("w1");
  });
});

describe("toggleMaximize", () => {
  it("最大化铺满视口减任务栏，还原恢复原矩形", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().toggleMaximize("w1");
    expect(s().windows.w1.isMaximized).toBe(true);
    expect(s().windows.w1.position).toEqual({ x: 0, y: 0 });
    expect(s().windows.w1.size).toEqual({
      width: window.innerWidth,
      height: window.innerHeight - TASKBAR_HEIGHT,
    });
    s().toggleMaximize("w1");
    expect(s().windows.w1.isMaximized).toBe(false);
    expect(s().windows.w1.position).toEqual({ x: 100, y: 100 });
    expect(s().windows.w1.size).toEqual({ width: 400, height: 300 });
  });
});

describe("bringToFront / z 序", () => {
  it("后聚焦的窗口 zIndex 单调递增", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().openWindow(descriptor({ id: "w2", title: "窗口二" }));
    const zBefore = s().windows.w1.zIndex;
    s().bringToFront("w1");
    expect(s().windows.w1.zIndex).toBeGreaterThan(s().windows.w2.zIndex);
    expect(s().windows.w1.zIndex).toBeGreaterThanOrEqual(zBefore);
    expect(s().activeId).toBe("w1");
  });
});

describe("cascadeWindows", () => {
  it("打开的窗口按 28px 层叠重排，从 (40,40) 起", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor({ id: "a", title: "甲", defaultPosition: { x: 5, y: 5 } }));
    s().openWindow(descriptor({ id: "b", title: "乙", defaultPosition: { x: 300, y: 88 } }));
    s().openWindow(descriptor({ id: "c", title: "丙", defaultPosition: { x: 120, y: 240 } }));
    s().minimizeWindow("c");
    s().cascadeWindows();
    expect(s().windows.a.position).toEqual({ x: 40, y: 40 });
    expect(s().windows.b.position).toEqual({ x: 68, y: 68 });
    expect(s().windows.c.position).toEqual({ x: 96, y: 96 });
    // 最小化的窗口被带回桌面，尺寸保持默认
    expect(s().windows.c.isMinimized).toBe(false);
    expect(s().windows.c.size).toEqual({ width: 400, height: 300 });
  });
});

describe("tileWindows", () => {
  it("≥2 窗按两列网格平铺，单元格 = (视口宽 × 视口高-任务栏) 均分", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor({ id: "a", title: "甲" }));
    s().openWindow(descriptor({ id: "b", title: "乙" }));
    s().openWindow(descriptor({ id: "c", title: "丙" }));
    s().tileWindows();
    const cellW = Math.floor(window.innerWidth / 2);
    const cellH = Math.floor((window.innerHeight - TASKBAR_HEIGHT) / 2);
    expect(s().windows.a.position).toEqual({ x: 0, y: 0 });
    expect(s().windows.a.size).toEqual({ width: cellW, height: cellH });
    expect(s().windows.b.position).toEqual({ x: cellW, y: 0 });
    expect(s().windows.c.position).toEqual({ x: 0, y: cellH });
    expect(s().windows.c.size).toEqual({ width: cellW, height: cellH });
  });

  it("单窗平铺为整面（一列）", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().tileWindows();
    expect(s().windows.w1.position).toEqual({ x: 0, y: 0 });
    expect(s().windows.w1.size).toEqual({
      width: window.innerWidth,
      height: window.innerHeight - TASKBAR_HEIGHT,
    });
  });
});

describe("minimizeAll", () => {
  it("最小化全部窗口并清除聚焦", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor());
    s().openWindow(descriptor({ id: "w2", title: "窗口二" }));
    expect(s().activeId).toBe("w2");
    s().minimizeAll();
    expect(s().windows.w1.isMinimized).toBe(true);
    expect(s().windows.w2.isMinimized).toBe(true);
    expect(s().activeId).toBeNull();
    // 窗口仍在册（任务栏可还原）
    expect(s().order).toEqual(["w1", "w2"]);
  });
});

describe("closeAllWindows", () => {
  it("关闭全部窗口，仅保留登录窗", () => {
    const s = () => useWindowManager.getState();
    s().openWindow(descriptor({ id: "login", title: "平台登录" }));
    s().openWindow(descriptor({ id: "mod:core", title: "首页/系统" }));
    s().openWindow(descriptor({ id: "mod:agent", title: "主管 Agent" }));
    s().closeAllWindows();
    expect(Object.keys(s().windows)).toEqual(["login"]);
    expect(s().order).toEqual(["login"]);
    expect(s().activeId).toBeNull();
  });
});
