import { useEffect } from "react";
import { Desktop } from "@/components/desktop/Desktop";
import { DesktopIcon } from "@/components/desktop/DesktopIcon";
import {
  ChartGlyph,
  DocGlyph,
  SearchGlyph,
  TableGlyph,
  TerminalGlyph,
} from "@/components/icons";
import DashboardContent from "@/pages/dashboard";
import CatalogContent from "@/pages/catalog";
import ReviewContent from "@/pages/review";
import ConsoleContent from "@/pages/console";
import ExperimentsContent from "@/pages/experiments";
import {
  useWindowManager,
  type WindowDescriptor,
} from "@/store/windowStore";

/* ============================================================================
   产品桌面：五个产品窗口的接线层
   —— 默认打开三个：产品仪表盘 / SKU 目录 / 标注审核
   —— 仅桌面图标打开两个：识别控制台 / 实验与发布门
   窗口内容全部来自 src/pages/*（当前为 v2 样本数据），
   正式内容替换对应页面文件即可，接线层无需改动。
   ========================================================================== */

/** 默认打开的三个窗口（首屏布局：左大右双叠）。 */
const DEFAULT_WINDOWS: WindowDescriptor[] = [
  {
    id: "dashboard",
    title: "产品仪表盘",
    icon: <ChartGlyph className="h-3.5 w-3.5" />,
    defaultPosition: { x: 32, y: 32 },
    defaultSize: { width: 760, height: 620 },
    minWidth: 560,
    minHeight: 480,
    content: <DashboardContent />,
  },
  {
    id: "catalog",
    title: "SKU 目录",
    icon: <TableGlyph className="h-3.5 w-3.5" />,
    defaultPosition: { x: 808, y: 32 },
    defaultSize: { width: 600, height: 430 },
    minWidth: 480,
    minHeight: 360,
    content: <CatalogContent />,
  },
  {
    id: "review",
    title: "标注审核",
    icon: <SearchGlyph className="h-3.5 w-3.5" />,
    defaultPosition: { x: 808, y: 478 },
    defaultSize: { width: 600, height: 372 },
    minWidth: 480,
    minHeight: 320,
    content: <ReviewContent />,
  },
];

/** 仅从桌面图标打开的两个窗口（最小尺寸走 store 默认 320×200）。 */
const LAUNCH_ONLY_WINDOWS: WindowDescriptor[] = [
  {
    id: "console",
    title: "识别控制台",
    icon: <TerminalGlyph className="h-3.5 w-3.5" />,
    defaultPosition: { x: 240, y: 180 },
    defaultSize: { width: 640, height: 460 },
    content: <ConsoleContent />,
  },
  {
    id: "experiments",
    title: "实验与发布门",
    icon: <DocGlyph className="h-3.5 w-3.5" />,
    defaultPosition: { x: 420, y: 140 },
    defaultSize: { width: 560, height: 420 },
    content: <ExperimentsContent />,
  },
];

/** 桌面图标栏清单：全部五个窗口（含默认打开的三个）。 */
const ALL_WINDOWS: WindowDescriptor[] = [
  ...DEFAULT_WINDOWS,
  ...LAUNCH_ONLY_WINDOWS,
];

export default function DemoDesktop() {
  const openWindow = useWindowManager((s) => s.openWindow);

  useEffect(() => {
    DEFAULT_WINDOWS.forEach((d) => openWindow(d));
  }, [openWindow]);

  return (
    <Desktop>
      {/* 桌面图标栏：列出全部五个窗口，关闭后可从这里重新打开 */}
      <div className="flex w-fit flex-col gap-1 p-3">
        {ALL_WINDOWS.map((d) => (
          <DesktopIcon key={d.id} descriptor={d} label={d.title} />
        ))}
      </div>
    </Desktop>
  );
}
