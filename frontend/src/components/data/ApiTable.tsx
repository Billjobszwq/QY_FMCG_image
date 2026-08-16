/**
 * ApiTable：通用数据表格原语（v3 基础层）。
 *
 * 状态纪律：
 * —— loading → HedgehogLoader 行（禁通用旋转圈）；
 * —— error   → ErrorState（serious 徽章 + 重试）；
 * —— empty   → HedgehogMascot 小尺寸 + emptyText；
 * —— 401 请改用 NeedLoginState 由页面层呈现。
 *
 * 密度纪律：表头 text-xs secondary、行 py-1.5 text-[13px]、
 * odd 行底纹、数值右对齐 tabular-nums；细边框小圆角。
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { HedgehogLoader } from "@/components/ui/loader";
import { HedgehogMascot } from "@/components/ui/mascot";
import { ErrorState } from "./ErrorState";

export type ColAlign = "left" | "right" | "center";

export interface ApiTableCol<T> {
  /** 取值键（row[key]）；render 提供时仅用于 key。 */
  key: string;
  /** 表头文案。 */
  label: string;
  /** 自定义渲染；缺省按 row[key] 原样呈现。 */
  render?: (row: T) => ReactNode;
  /** 对齐；right 自动附加 tabular-nums（数值列）。 */
  align?: ColAlign;
}

/** 缺省单元格取值：空值统一显示破折号，对象回退 JSON。 */
function cellValue(row: unknown, key: string): ReactNode {
  const v = (row as Record<string, unknown>)[key];
  if (v === null || v === undefined || v === "") {
    return <span className="text-text-secondary">—</span>;
  }
  if (typeof v === "number" || typeof v === "boolean" || typeof v === "string") {
    return String(v);
  }
  return JSON.stringify(v);
}

const ALIGN_CLASSES: Record<ColAlign, string> = {
  left: "text-left",
  right: "text-right tabular-nums",
  center: "text-center",
};

export function ApiTable<T>({
  rows,
  cols,
  loading = false,
  error = null,
  onRetry,
  emptyText = "暂无数据",
  rowKey,
  className,
}: {
  rows: T[];
  cols: ApiTableCol<T>[];
  /** 加载中：渲染 HedgehogLoader 行。 */
  loading?: boolean;
  /** 错误对象：非空时渲染 ErrorState + 重试。 */
  error?: unknown;
  /** 重试回调（error 态按钮）。 */
  onRetry?: () => void;
  /** 空态文案。 */
  emptyText?: string;
  /** 行 key 提取；缺省优先 id / *_id 字段，再退回下标。 */
  rowKey?: (row: T, index: number) => string;
  className?: string;
}) {
  const keyOf = (row: T, index: number): string => {
    if (rowKey) return rowKey(row, index);
    const rec = row as Record<string, unknown>;
    for (const k of ["id", "task_id", "run_id", "name"]) {
      const v = rec[k];
      if (typeof v === "string" || typeof v === "number") return String(v);
    }
    return String(index);
  };

  return (
    <div
      className={cn(
        "overflow-x-auto rounded-md border border-border bg-background",
        className,
      )}
    >
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-border">
            {cols.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={cn(
                  "px-2.5 py-1.5 text-xs font-medium text-text-secondary whitespace-nowrap",
                  ALIGN_CLASSES[col.align ?? "left"],
                )}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={cols.length} className="px-2.5 py-6">
                <div className="flex justify-center">
                  <HedgehogLoader className="h-8 w-auto" />
                </div>
              </td>
            </tr>
          ) : error ? (
            <tr>
              <td colSpan={cols.length} className="px-2.5">
                <ErrorState
                  message={error instanceof Error ? error.message : undefined}
                  onRetry={onRetry}
                />
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={cols.length} className="px-2.5 py-6">
                <div className="flex flex-col items-center gap-1.5">
                  <HedgehogMascot className="h-16 w-auto" />
                  <p className="text-xs text-text-secondary">{emptyText}</p>
                </div>
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr
                key={keyOf(row, index)}
                className="border-b border-border/60 last:border-0 odd:bg-surface/70"
              >
                {cols.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      "px-2.5 py-1.5 text-[13px] text-text-primary",
                      ALIGN_CLASSES[col.align ?? "left"],
                    )}
                  >
                    {col.render ? col.render(row) : cellValue(row, col.key)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
