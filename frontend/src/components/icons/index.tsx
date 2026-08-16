/**
 * 图标库：占位图标库已升级为统一手工几何图标，待正式图标库替换。
 *
 * 统一规格：
 * —— viewBox 一律 "0 0 16 16"；笔画一律 stroke="currentColor"，
 *    颜色跟随父级文字色（hover / focus / 选中态的状态色由父级控制，
 *    图标自身不硬编码任何颜色，无渐变、无大面积填充）
 * —— strokeWidth 1.3–1.5，strokeLinecap / strokeLinejoin 均为 round（圆头手绘感）
 * —— 标题栏四枚（Close / Minimize / Maximize / Restore）默认 12px（h-3），
 *    保证 16 网格下笔画可读；其余默认 16px（h-4 w-4），可用 className 覆盖
 * —— 纯装饰用途一律 aria-hidden；仅 HedgehogMark 作为交互按钮带 aria-label
 */

/** 图标通用 props：可选 className，覆盖默认尺寸。 */
type GlyphProps = {
  className?: string;
};

/** 窗口标题栏关闭（×）：两条交叉线，交点略偏中心制造手绘感。 */
export function CloseGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-3 w-3"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3.6 3.4 L12.4 12.5 M12.5 3.6 L3.5 12.4" />
    </svg>
  );
}

/** 窗口标题栏最小化（—）：水平短线上弧微弯，拒绝死直线。 */
export function MinimizeGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-3 w-3"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* Q 控制点略高于两端，中段上拱约 0.3px */}
      <path d="M3.2 8.9 Q7.8 8.3 12.8 8.9" />
    </svg>
  );
}

/** 窗口标题栏最大化（□）：单线圆角矩形，不填充。 */
export function MaximizeGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-3 w-3"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 宽高略不对称，保留手工感 */}
      <rect x="3.1" y="3.4" width="9.8" height="9.4" rx="1.5" />
    </svg>
  );
}

/** 窗口标题栏还原：前后叠两框；后框只画露出的上 / 右两段折线，层次靠线条不靠填充。 */
export function RestoreGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-3 w-3"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 后框：顶部横线 + 圆角折点 + 右侧竖线 */}
      <path d="M5.4 2.9 H11.2 Q13.1 2.9 13.1 4.8 V10.6" />
      {/* 前框：完整圆角矩形 */}
      <rect x="2.7" y="5.3" width="8.2" height="8" rx="1.4" />
    </svg>
  );
}

/**
 * 默认窗口 / 应用图标（任务栏与桌面图标的 fallback）：
 * 窗口轮廓 + 标题栏分隔横线 + 一枚标题栏小圆点，直接呼应产品自身的窗口隐喻。
 */
export function AppGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="1.8" y="3.1" width="12.4" height="9.8" rx="2" />
      {/* 标题栏分隔横线 */}
      <path d="M1.8 6.3 H14.2" />
      {/* 标题栏小圆点（唯一填充，随 currentColor） */}
      <circle cx="4" cy="4.7" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** 文档窗口图标：折角文档 + 三条长短不一的文本线（末行最短）。 */
export function DocGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 文档轮廓（右上角留折角缺口） */}
      <path d="M9.9 1.9 H4.6 Q3.3 1.9 3.3 3.2 V12.8 Q3.3 14.1 4.6 14.1 H11.4 Q12.7 14.1 12.7 12.8 V4.7 Z" />
      {/* 折角 */}
      <path d="M9.9 1.9 V4.7 H12.7" />
      {/* 文本线：长短不一，末行最短 */}
      <path d="M5.6 7.3 H10.6 M5.6 9.4 H9.7 M5.6 11.5 H7.9" />
    </svg>
  );
}

/** 仪表盘 / 数据窗口图标：两轴短线 + 手绘折线趋势，转折处圆角折点。 */
export function ChartGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 坐标轴：略细一级，让位给趋势线 */}
      <path d="M3.1 2.6 V12.7 H13.5" strokeWidth="1.3" />
      {/* 趋势折线 */}
      <path d="M4.9 10 L7.3 7 L9.1 8.7 L12.6 4.5" />
    </svg>
  );
}

/** SKU 列表 / 表格窗口图标：3×3 网格，外框小圆角，内部线略短于框留出气口。 */
export function TableGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="1.9" y="3.1" width="12.2" height="9.8" rx="1.5" />
      {/* 内部两竖两横，两端各留约 1px 气口 */}
      <path d="M6 4.1 V11.9 M10 4.1 V11.9 M2.9 6.4 H13.1 M2.9 9.6 H13.1" />
    </svg>
  );
}

/** Agent / 控制台窗口图标：提示符『>』+ 下划线光标，两条笔画，辨识度靠负空间。 */
export function TerminalGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 提示符 > */}
      <path d="M3.4 5.1 L7 8 L3.4 10.9" />
      {/* 下划线光标 */}
      <path d="M8.8 10.9 H12.6" />
    </svg>
  );
}

/** 文件 / 导航类窗口图标：带标签突起的文件夹轮廓，单线不填充。 */
export function FolderGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 5.1 Q2 3.9 3.2 3.9 H6.1 L7.4 5.5 H12.8 Q14 5.5 14 6.7 V11.3 Q14 12.5 12.8 12.5 H3.2 Q2 12.5 2 11.3 Z" />
    </svg>
  );
}

/** 搜索入口：圆形镜片 + 45° 短柄，柄端圆帽出头一点，柄轻微偏轴带来手绘感。 */
export function SearchGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="7" cy="7" r="4.3" />
      {/* 柄的起点略偏离镜片的径向轴线 */}
      <path d="M10.3 10.1 L13.5 13.5" strokeWidth="1.5" />
    </svg>
  );
}

/** 设置窗口图标：三个滑块（两横一竖轨 + 圆钮），避开齿轮的模板化 SaaS 味。 */
export function SettingsGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 两条横轨 + 一条竖轨 */}
      <path d="M2.6 4.6 H10.9 M2.6 11.4 H10.9 M13.3 2.6 V13.4" />
      {/* 圆钮位置错开，呈现"手工调校"的随意感 */}
      <circle cx="8.6" cy="4.6" r="1.6" fill="currentColor" stroke="none" />
      <circle cx="4.9" cy="11.4" r="1.6" fill="currentColor" stroke="none" />
      <circle cx="13.3" cy="9.3" r="1.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** 快捷键帮助窗口入口：手绘问号 + 下点，问号尾部略弯不闭合。 */
export function HelpGlyph({ className }: GlyphProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={className ?? "h-4 w-4"}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 问号：起笔略歪，尾部自然收弯、不闭合 */}
      <path d="M5.4 5.4 Q5.3 3 8 3.1 Q10.7 3.2 10.6 5.4 Q10.5 7.2 8.5 7.9 Q8.1 8.1 8.05 9.9" />
      <circle cx="8.05" cy="12.5" r="0.95" fill="currentColor" stroke="none" />
    </svg>
  );
}

/**
 * 品牌刺猬标记：与 public/favicon.svg 同源——同一套 32 网格 path
 * （4 峰背刺折线 + 平底身体 + 负空间眼孔，fill-rule evenodd），
 * favicon 更新时需同步此处。currentColor 填充，在任务栏深底上由父级
 * 文字色决定呈现（如奶油色）。预留开始菜单 / 导航入口：button 语义 + aria-label。
 */
export function HedgehogMark({
  className,
  label = "开始菜单",
  onClick,
}: GlyphProps & {
  /** 无障碍名称（button 的 aria-label / title）。 */
  label?: string;
  /** 开始菜单 / 导航入口的点击回调（预留）。 */
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="accent-interactive inline-flex cursor-pointer items-center justify-center rounded-md focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
    >
      <svg
        viewBox="0 0 32 32"
        className={className ?? "h-4 w-4"}
        aria-hidden="true"
      >
        {/* 与 favicon 同源的刺猬侧面剪影；眼孔为 evenodd 负空间挖孔 */}
        <path
          fillRule="evenodd"
          d="M8 24 Q6.2 24 6.2 22.2 L6.2 16.5 L8.8 9.8 L11.2 13.2 L13.6 8.6 L16 12.6 L18.4 9.2 L20.4 12.8 L22.6 10.8 L24.2 14.8 L27.6 20.4 L25.4 24 Z M22.3 18 a1.3 1.3 0 1 0 2.6 0 a1.3 1.3 0 1 0 -2.6 0 Z"
          fill="currentColor"
        />
      </svg>
    </button>
  );
}
