import { cn } from "@/lib/utils";

/**
 * 静态刺猬吉祥物（Mascot）—— 空态插图。
 *
 * 用途与替换约定：
 * - 用于 NotesContent 等"这里很安静 / 还没有内容"的空态场景，
 *   替换旧的灰色 DocGlyph 占位图形；空态请统一复用本组件，
 *   不要再引入新的临时占位图形。
 * - 与 loader.tsx 的 HedgehogLoader 同源：同一套手工折线背刺、
 *   monoline 圆头线条；加载动画只用 HedgehogLoader，本组件纯静态、
 *   无任何动画（含 hedgehog-bob 呼吸也不启用）。
 * - 后续会升级为 components/illustrations/ 下的正式组件集
 *   （HedgehogEmpty / HedgehogError / HedgehogWelcome，供空态 / 错误 / 404
 *   复用）；本组件即 HedgehogEmpty 的雏形。
 *
 * 设计红线（改动必须遵守）：
 * - 颜色纪律：全图仅允许 --color-text-primary / --color-text-secondary /
 *   --color-surface / --color-border-strong 四个令牌色；
 *   严禁橙色（accent 只许出现在 hover / focus / 选中态）、
 *   严禁渐变、严禁毛玻璃。
 * - 画布 viewBox 0 0 160 100：刺猬占左侧约 60%，面朝右
 *   （只画正面与左右侧，禁画背面）；右侧 40% 留给台词牌。
 * - 装饰必须服务"空 / 安静"的叙事：台词牌 + 虚线地平线 +
 *   一朵两笔小草，不加其他元素。
 */
export function HedgehogMascot({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 160 100"
      role="img"
      aria-label="空态插图：一只小刺猬和台词牌 content goes here"
      className={cn("h-32 w-auto", className)}
    >
      {/* 地面：border-strong 虚线地平线（PostHog 式 dashed 分割） */}
      <line
        x1="8"
        y1="85"
        x2="152"
        y2="85"
        stroke="var(--color-border-strong)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeDasharray="7 6"
      />

      {/* 小草：两笔，脚下唯一的装饰，衬托"这里很空" */}
      <path
        d="M15 85 Q14 80 12 78 M15 85 Q16 79 18 77"
        fill="none"
        stroke="var(--color-text-secondary)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />

      {/* ---- 刺猬（面朝右，与 loader 同源） ---- */}
      {/* 背部尖刺：手工折线（先画，被身体盖住下缘） */}
      <path
        d="M24 72 L30 48 L38 64 L46 40 L54 60 L62 36 L70 60 L78 44 L86 68 Z"
        fill="var(--color-text-primary)"
      />
      {/* 身体：surface 填充 + 墨色 1.5px 描边，round join */}
      <path
        d="M20 72 Q20 58 40 56 Q64 54 84 66 L104 75 Q106 77 103 78 L24 78 Q20 78 20 72 Z"
        fill="var(--color-surface)"
        stroke="var(--color-text-primary)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {/* 短墩脚：无手指 */}
      <rect x="34" y="78" width="8" height="7" rx="3" fill="var(--color-text-primary)" />
      <rect x="68" y="78" width="8" height="7" rx="3" fill="var(--color-text-primary)" />
      {/* 眉毛：一根短线，克制的表情（错误态才做内低外高） */}
      <line
        x1="85.8"
        y1="63.8"
        x2="91.2"
        y2="63"
        stroke="var(--color-text-primary)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      {/* 眼睛：墨色圆点 */}
      <circle cx="89" cy="69" r="2.6" fill="var(--color-text-primary)" />
      {/* 鼻子：墨色圆点 */}
      <circle cx="105" cy="76" r="3.2" fill="var(--color-text-primary)" />

      {/* ---- 台词牌（贴纸美学：奶油底 + 墨色细边 + 2px 硬投影，整体 -2°） ---- */}
      <g transform="rotate(-2 130 37)">
        {/* 硬投影：2px 实偏移，非模糊 */}
        <rect x="104" y="26" width="56" height="26" rx="5" fill="var(--color-text-primary)" />
        {/* 牌面 */}
        <rect
          x="102"
          y="24"
          width="56"
          height="26"
          rx="5"
          fill="var(--color-surface)"
          stroke="var(--color-text-primary)"
          strokeWidth="1"
        />
        {/* 台词：squeak 手写字体，text-secondary 令牌色 */}
        <text
          textAnchor="middle"
          fontFamily="var(--font-squeak)"
          fontSize="7"
          fontWeight="700"
          fill="var(--color-text-secondary)"
        >
          <tspan x="130" y="35.5">
            content
          </tspan>
          <tspan x="130" dy="9">
            goes here
          </tspan>
        </text>
      </g>
    </svg>
  );
}
