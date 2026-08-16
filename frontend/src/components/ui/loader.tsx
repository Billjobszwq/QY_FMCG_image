import { cn } from "@/lib/utils";

/**
 * 加载状态：手绘刺猬动画（拒绝通用旋转圈）。
 * 纯 SVG + CSS keyframes，无依赖。
 */
export function HedgehogLoader({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 40"
      role="status"
      aria-label="加载中"
      className={cn("h-9 w-auto", className)}
    >
      <g
        style={{
          animation: "hedgehog-bob 0.9s ease-in-out infinite",
          transformOrigin: "center bottom",
        }}
      >
        {/* 背部尖刺（手工折线，非模板素材） */}
        <path
          d="M12 27 L15 15 L19 23 L23 11 L27 21 L31 9 L35 21 L39 13 L43 25 Z"
          fill="var(--color-text-primary)"
        />
        {/* 身体 */}
        <path
          d="M10 27 Q10 20 20 19 Q32 18 42 24 L52 28.5 Q53 29.5 51.5 30 L12 30 Q10 30 10 27 Z"
          fill="var(--color-surface)"
          stroke="var(--color-text-primary)"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        {/* 眼睛 */}
        <circle cx="44.5" cy="25.5" r="1.3" fill="var(--color-text-primary)" />
        {/* 鼻子（嗅探动画） */}
        <g
          style={{
            animation: "hedgehog-sniff 0.9s ease-in-out infinite",
            transformOrigin: "48px 28px",
          }}
        >
          <circle cx="52.5" cy="29" r="1.6" fill="var(--color-text-primary)" />
        </g>
        {/* 脚 */}
        <rect x="17" y="30" width="4" height="3.5" rx="1.5" fill="var(--color-text-primary)" />
        <rect x="34" y="30" width="4" height="3.5" rx="1.5" fill="var(--color-text-primary)" />
      </g>
    </svg>
  );
}

/** 脉冲点加载（更轻量的场景）。 */
export function PulseDots({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="加载中"
      className={cn("inline-flex items-center gap-1", className)}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="inline-block h-1.5 w-1.5 rounded-full bg-text-secondary"
          style={{
            animation: `pulse-dot 1s ease-in-out ${i * 0.16}s infinite`,
          }}
        />
      ))}
    </span>
  );
}
