/**
 * 模块工作台标签页 store（v5 交互范式）。
 *
 * —— 桌面图标 = 应用（一个模块分组一个窗口），窗口内部用标签页承载
 *    子功能；每个分组记住当前激活的标签路由；
 * —— setTab：窗口内点击标签时写入；
 * —— requestTab：跨窗口跳转入口（与 setTab 同一实现）——例如顶部菜单栏
 *    健康点 → 首页组的 /status 标签、帮助菜单 → 帮助组的 /help 标签；
 *    调用方在 requestTab 之后再开窗 / 置前对应分组窗口即可。
 *
 * 缺省语义：tabs 中无记录时由 ModuleWorkbench 回退到组内第一个条目。
 */
import { create } from "zustand";

interface ModuleTabsState {
  /** groupKey → 当前激活标签的路由键。 */
  tabs: Record<string, string>;
  /** 写入某分组的激活标签。 */
  setTab: (groupKey: string, route: string) => void;
  /** 外部跳转入口：语义同 setTab（健康点 / 帮助菜单等跨窗口调用）。 */
  requestTab: (groupKey: string, route: string) => void;
}

export const useModuleTabs = create<ModuleTabsState>()((set) => {
  const setTab = (groupKey: string, route: string) =>
    set((s) =>
      s.tabs[groupKey] === route ? {} : { tabs: { ...s.tabs, [groupKey]: route } },
    );
  return {
    tabs: {},
    setTab,
    requestTab: setTab,
  };
});
