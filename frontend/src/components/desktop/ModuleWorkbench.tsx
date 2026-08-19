/**
 * 模块工作台（v5 交互范式）：一个分组 = 一个窗口，窗口内用标签页承载子功能。
 *
 * —— 顶部标签栏（h-9 / border-b / bg-surface）：
 *    标签按钮 hover 变 accent；选中 = 2px accent 下划线 + text-primary
 *    （selected 态允许使用 accent）；
 * —— 激活标签存 moduleTabs store（供外部跳转：健康点 → 首页组 /status 等）；
 * —— 内容 = Suspense（刺猬加载兜底）+ 懒加载页面；
 * —— 单条目分组不渲染标签栏，直接呈现页面。
 */
import { Suspense } from "react";
import { cn } from "@/lib/utils";
import { MODULE_GROUPS } from "@/modules/registry";
import { useModuleTabs } from "@/store/moduleTabs";
import { HedgehogLoader } from "@/components/ui/loader";

export interface ModuleWorkbenchProps {
  /** 分组键（MODULE_GROUPS[].group），窗口 id 约定为 "mod:" + groupKey。 */
  groupKey: string;
}

export function ModuleWorkbench({ groupKey }: ModuleWorkbenchProps) {
  const activeRoute = useModuleTabs((s) => s.tabs[groupKey]);
  const setTab = useModuleTabs((s) => s.setTab);
  const group = MODULE_GROUPS.find((g) => g.group === groupKey);
  if (!group) return null;

  // 缺省回退到组内第一个条目（tabs 未写入时）。
  const active =
    group.items.find((i) => i.route === activeRoute) ?? group.items[0];
  const Page = active.Page;

  return (
    <div className="flex h-full w-full flex-col">
      {group.items.length > 1 && (
        <div
          role="tablist"
          aria-label={`${group.label}标签页`}
          className="flex h-9 shrink-0 items-stretch gap-1 border-b border-border bg-surface px-2"
        >
          {group.items.map((item) => {
            const selected = item.route === active.route;
            return (
              <button
                key={item.route}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setTab(group.group, item.route)}
                className={cn(
                  "flex min-w-0 cursor-pointer items-center gap-1.5 border-b-2 px-2 text-[13px]",
                  "outline-none transition-colors duration-200 ease-out",
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
                  selected
                    ? "border-accent text-text-primary"
                    : "border-transparent text-text-secondary hover:text-accent",
                )}
              >
                <span className="shrink-0">{item.icon}</span>
                <span className="truncate">{item.label}</span>
              </button>
            );
          })}
        </div>
      )}
      <div className="min-h-0 flex-1">
        <Suspense
          fallback={
            <div className="flex h-full w-full items-center justify-center">
              <HedgehogLoader />
            </div>
          }
        >
          <Page />
        </Suspense>
      </div>
    </div>
  );
}

export default ModuleWorkbench;
