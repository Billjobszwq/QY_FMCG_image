/**
 * SKU 目录页（窗口内容组件，不含窗口壳）。
 *
 * 布局：
 * 1) 工具行 —— 搜索框（代码/名称）+ 状态过滤下拉 + 右侧计数（样本标注）
 * 2) 高密度表格 —— text-[13px]、odd 行浅面板底、表头次级文字底边框
 * 3) 空结果态 —— 刺猬吉祥物 + 「没有匹配的 SKU」
 *
 * 设计红线：
 * —— accent 橙仅出现在交互态（名称 hover 走 .accent-interactive）
 * —— 颜色一律令牌；状态色只经 StatusBadge（图标 + 文字）
 */
import { useMemo, useState } from "react";
import { SKUS, type SkuStatus } from "@/data/sample";
import { StatusBadge, type StatusTone } from "@/components/charts/primitives";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { HedgehogMascot } from "@/components/ui/mascot";

/* ============================================================================
   status 中文映射（集中在文件内，避免散落）
   ========================================================================== */

/** status → 徽章文案 + tone（状态保留色仅由 StatusBadge 消费） */
const STATUS_META: Record<SkuStatus, { label: string; tone: StatusTone }> = {
  active: { label: "在库", tone: "good" },
  graylist: { label: "灰名单", tone: "warn" },
  pending: { label: "待 ingest", tone: "muted" },
  rejected: { label: "已驳回", tone: "serious" },
};

/** 状态过滤取值：全部 + 四种库内状态 */
type StatusFilter = "all" | SkuStatus;

/* ============================================================================
   页面内容
   ========================================================================== */

export default function CatalogContent() {
  // 搜索词（命中 SKU 编码或名称，忽略大小写）
  const [query, setQuery] = useState("");
  // 状态过滤（默认全部）
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  // 受控过滤：搜索 + 状态双重条件
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return SKUS.filter((sku) => {
      if (statusFilter !== "all" && sku.status !== statusFilter) return false;
      if (!q) return true;
      return (
        sku.id.toLowerCase().includes(q) || sku.name.toLowerCase().includes(q)
      );
    });
  }, [query, statusFilter]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* ---- 1) 工具行：搜索 + 状态过滤 + 计数 ---- */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索 SKU / 名称…"
          aria-label="搜索 SKU"
          className="w-56"
        />
        <Select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          aria-label="状态过滤"
          className="w-32"
        >
          <option value="all">全部</option>
          {(Object.keys(STATUS_META) as SkuStatus[]).map((s) => (
            <option key={s} value={s}>
              {STATUS_META[s].label}
            </option>
          ))}
        </Select>
        {/* 右侧计数：样本数据显式标注 */}
        <span className="ml-auto text-xs text-text-secondary">
          共 {filtered.length} · 样本
        </span>
      </div>

      {/* ---- 2) 高密度表格 / 3) 空结果态 ---- */}
      <div className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          /* 空结果态：吉祥物居中 + 次级文字 */
          <div className="flex h-full flex-col items-center justify-center gap-2 py-16 text-center">
            <HedgehogMascot className="h-24" />
            <p className="text-sm text-text-secondary">没有匹配的 SKU</p>
          </div>
        ) : (
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">代码</th>
                <th className="px-3 py-2 font-medium">名称</th>
                <th className="px-3 py-2 font-medium">类目</th>
                <th className="px-3 py-2 font-medium">条码</th>
                <th className="px-3 py-2 text-right font-medium">近 14 天识别</th>
                <th className="px-3 py-2 text-right font-medium">准确率</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-4 py-2 text-right font-medium">更新时间</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((sku) => (
                <tr
                  key={sku.id}
                  className="border-b border-border/70 odd:bg-surface/60 last:border-b-0"
                >
                  {/* 代码：等宽 */}
                  <td className="px-4 py-1.5 font-mono whitespace-nowrap">
                    {sku.id}
                  </td>
                  {/* 名称：链接样式，hover 切 accent（accent 仅交互态） */}
                  <td className="px-3 py-1.5">
                    <span className="accent-interactive cursor-pointer">
                      {sku.name}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    {sku.category}
                  </td>
                  {/* 条码：等宽 + 次级色，不与主信息抢层级 */}
                  <td className="px-3 py-1.5 font-mono text-text-secondary whitespace-nowrap">
                    {sku.barcode}
                  </td>
                  {/* 数值列：右对齐 + 表格数字 */}
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {sku.detections14d.toLocaleString("zh-CN")}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {sku.precisionPct.toFixed(1)}%
                  </td>
                  <td className="px-3 py-1.5">
                    <StatusBadge tone={STATUS_META[sku.status].tone}>
                      {STATUS_META[sku.status].label}
                    </StatusBadge>
                  </td>
                  <td className="px-4 py-1.5 text-right text-text-secondary whitespace-nowrap tabular-nums">
                    {sku.updatedAt}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
