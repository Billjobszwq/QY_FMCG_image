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
