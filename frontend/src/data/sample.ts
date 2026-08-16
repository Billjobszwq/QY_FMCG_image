/**
 * 样本数据，仅供 UI 展示，非生产口径。
 *
 * 数值锚定真实 E0 基线（docs/experiments/E0-current-bundle-baseline.md）：
 * —— accepted precision 89.0% / 端到端召回 20.3% / review 比例 10.5% / 每张片 FP 3.174
 * —— bundle：prod_20260804_v4_r2；评测集：dev_v1（n=800）；阈值：conf 0.6 / margin 0.05
 */

/* ============================================================================
   E0 基线指标
   ========================================================================== */

export interface BaselineMetrics {
  /** 线上识别包版本 */
  bundle: string;
  /** 评测集名称 */
  evalSet: string;
  /** 评测集照片数 */
  evalSize: number;
  /** 置信度阈值（低于则不直收） */
  confThreshold: number;
  /** 领先间距阈值（top1 与 top2 之差） */
  marginThreshold: number;
  /** accepted 结果中的准确率（%） */
  acceptedPrecisionPct: number;
  /** 端到端召回：accepted 且正确 / GT（%） */
  endToEndRecallPct: number;
  /** 已匹配结果中进入人工审核的比例（%） */
  reviewRatioPct: number;
  /** 每张照片平均误报数 */
  fpPerPhoto: number;
}

export const BASELINE: BaselineMetrics = {
  bundle: "prod_20260804_v4_r2",
  evalSet: "dev_v1",
  evalSize: 800,
  confThreshold: 0.6,
  marginThreshold: 0.05,
  acceptedPrecisionPct: 89.0,
  endToEndRecallPct: 20.3,
  reviewRatioPct: 10.5,
  fpPerPhoto: 3.174,
};

/* ============================================================================
   错误账本（E0 评测集累计，按数量降序）
   ========================================================================== */

export type ErrorKind =
  | "miss"
  | "category_confusion"
  | "fp_accepted"
  | "known_false_reject"
  | "fp_review"
  | "unknown_review"
  | "unknown_false_accept";

export interface ErrorLedgerEntry {
  /** 错误类别键（与后端口径一致） */
  kind: ErrorKind;
  /** 中文展示名 */
  label: string;
  /** 累计条数 */
  count: number;
}

export const ERROR_LEDGER: ErrorLedgerEntry[] = [
  { kind: "miss", label: "漏检", count: 15135 },
  { kind: "fp_accepted", label: "误报直收", count: 2190 },
  { kind: "known_false_reject", label: "已知误拒", count: 501 },
  { kind: "category_confusion", label: "分类混淆", count: 439 },
  { kind: "fp_review", label: "误报进审", count: 349 },
  { kind: "unknown_false_accept", label: "未知误收", count: 70 },
  { kind: "unknown_review", label: "未知进审", count: 42 },
];

/* ============================================================================
   SKU 主数据（货架快消品，status 含 graylist / pending / rejected 分布）
   ========================================================================== */

export type SkuStatus = "active" | "graylist" | "pending" | "rejected";

export interface SkuSample {
  /** SKU 编码 */
  id: string;
  /** 品名（含规格） */
  name: string;
  /** 类目 */
  category: string;
  /** 13 位条码 */
  barcode: string;
  /** 库内状态 */
  status: SkuStatus;
  /** 近 14 天识别次数 */
  detections14d: number;
  /** 该 SKU 识别准确率（%） */
  precisionPct: number;
  /** 最近更新时间 */
  updatedAt: string;
}

export const SKUS: SkuSample[] = [
  { id: "SKU-1001", name: "可口可乐 330ml 罐", category: "碳酸饮料", barcode: "6901939621035", status: "active", detections14d: 1642, precisionPct: 96.8, updatedAt: "2026-08-14 18:22" },
  { id: "SKU-1002", name: "农夫山泉 550ml", category: "饮用水", barcode: "6921168500116", status: "active", detections14d: 1518, precisionPct: 95.2, updatedAt: "2026-08-14 18:22" },
  { id: "SKU-1003", name: "伊利纯牛奶 250ml", category: "常温奶", barcode: "6907992501628", status: "active", detections14d: 1436, precisionPct: 94.1, updatedAt: "2026-08-14 17:05" },
  { id: "SKU-1004", name: "康师傅冰红茶 500ml", category: "茶饮料", barcode: "6920698430112", status: "active", detections14d: 1294, precisionPct: 93.7, updatedAt: "2026-08-14 17:05" },
  { id: "SKU-1005", name: "乐事原味 70g", category: "膨化食品", barcode: "6924743913829", status: "active", detections14d: 1103, precisionPct: 91.9, updatedAt: "2026-08-13 21:40" },
  { id: "SKU-1006", name: "红牛维生素功能饮料 250ml 罐", category: "功能饮料", barcode: "6920202888883", status: "active", detections14d: 987, precisionPct: 92.4, updatedAt: "2026-08-13 21:40" },
  { id: "SKU-1007", name: "奥利奥经典原味 97g", category: "饼干", barcode: "6901668962919", status: "active", detections14d: 861, precisionPct: 90.6, updatedAt: "2026-08-12 19:11" },
  { id: "SKU-1008", name: "王老吉凉茶 310ml 罐", category: "凉茶", barcode: "6901028089296", status: "active", detections14d: 724, precisionPct: 89.5, updatedAt: "2026-08-12 19:11" },
  { id: "SKU-1009", name: "海天金标生抽 500ml", category: "调味品", barcode: "6902088100012", status: "active", detections14d: 668, precisionPct: 88.3, updatedAt: "2026-08-11 16:48" },
  { id: "SKU-1010", name: "统一 100 老坛酸菜牛肉面 桶装", category: "方便面", barcode: "6925303730215", status: "graylist", detections14d: 342, precisionPct: 76.2, updatedAt: "2026-08-10 14:03" },
  { id: "SKU-1011", name: "蒙牛特仑苏 250ml", category: "常温奶", barcode: "6907992513201", status: "pending", detections14d: 128, precisionPct: 71.5, updatedAt: "2026-08-09 10:26" },
  { id: "SKU-1012", name: "雪花勇闯天涯 500ml 罐", category: "啤酒", barcode: "6901285948868", status: "rejected", detections14d: 12, precisionPct: 41.0, updatedAt: "2026-08-08 09:14" },
];

/* ============================================================================
   近 14 天日度量（照片量 300–600 波动；accepted/review/rejected 为识别结果
   拆分，review 占比约 10.5%，与基线大致自洽）
   ========================================================================== */

export interface DailyVolumeSample {
  /** 日期（ISO） */
  date: string;
  /** 当日照片量 */
  photos: number;
  /** 直接采纳的识别结果数 */
  accepted: number;
  /** 进入人工审核的结果数 */
  review: number;
  /** 被拒绝的结果数 */
  rejected: number;
}

export const DAILY: DailyVolumeSample[] = [
  { date: "2026-08-01", photos: 428, accepted: 4566, review: 604, rejected: 610 },
  { date: "2026-08-02", photos: 396, accepted: 4224, review: 559, rejected: 563 },
  { date: "2026-08-03", photos: 361, accepted: 3850, review: 512, rejected: 512 },
  { date: "2026-08-04", photos: 512, accepted: 5460, review: 726, rejected: 726 },
  { date: "2026-08-05", photos: 587, accepted: 6261, review: 832, rejected: 832 },
  { date: "2026-08-06", photos: 463, accepted: 4938, review: 656, rejected: 657 },
  { date: "2026-08-07", photos: 342, accepted: 3647, review: 485, rejected: 485 },
  { date: "2026-08-08", photos: 389, accepted: 4149, review: 551, rejected: 552 },
  { date: "2026-08-09", photos: 544, accepted: 5802, review: 771, rejected: 771 },
  { date: "2026-08-10", photos: 578, accepted: 6164, review: 819, rejected: 820 },
  { date: "2026-08-11", photos: 495, accepted: 5280, review: 702, rejected: 701 },
  { date: "2026-08-12", photos: 431, accepted: 4597, review: 611, rejected: 611 },
  { date: "2026-08-13", photos: 566, accepted: 6036, review: 802, rejected: 803 },
  { date: "2026-08-14", photos: 509, accepted: 5429, review: 722, rejected: 721 },
];

/* ============================================================================
   识别漏斗（自 8000 张照片起，逐级单调递减）
   ========================================================================== */

export interface FunnelStage {
  /** 阶段名称 */
  label: string;
  /** 通过该阶段的数量 */
  value: number;
}

export const FUNNEL: FunnelStage[] = [
  { label: "照片上传", value: 8000 },
  { label: "质量预检通过", value: 7468 },
  { label: "检出候选框", value: 6903 },
  { label: "置信度通过（conf≥0.6）", value: 5617 },
  { label: "间距通过（margin≥0.05）", value: 4826 },
  { label: "最终 accepted", value: 4312 },
];

/* ============================================================================
   评测运行记录（5 条：含 1 条 running、1 条 gate-failed）
   ========================================================================== */

export type RunStatus = "finished" | "running" | "gate-failed";

export interface RunSample {
  /** 运行编号 */
  id: string;
  /** 被测识别包 */
  bundle: string;
  /** 评测集 */
  evalSet: string;
  /** 评测照片数 */
  n: number;
  /** 运行状态 */
  status: RunStatus;
  /** 开始时间 */
  startedAt: string;
  /** 耗时（分钟）；running 时为 null */
  durationMin: number | null;
  /** accepted precision（%）；running 时为 null */
  precisionPct: number | null;
  /** 端到端召回（%）；running 时为 null */
  recallPct: number | null;
  /** 门禁结论 */
  gate: string;
}

export const RUNS: RunSample[] = [
  { id: "run-0815-04", bundle: "exp_e1_margin008_r1", evalSet: "dev_v1", n: 800, status: "running", startedAt: "2026-08-15 09:42", durationMin: null, precisionPct: null, recallPct: null, gate: "评测进行中" },
  { id: "run-0815-03", bundle: "prod_20260804_v4_r2", evalSet: "dev_v1", n: 800, status: "finished", startedAt: "2026-08-15 07:10", durationMin: 38, precisionPct: 89.0, recallPct: 20.3, gate: "无回退，门禁通过" },
  { id: "run-0814-02", bundle: "exp_e0_conf055_r1", evalSet: "dev_v1", n: 800, status: "gate-failed", startedAt: "2026-08-14 22:31", durationMin: 41, precisionPct: 84.1, recallPct: 18.9, gate: "precision 低于基线 1pt 以上，门禁拦截" },
  { id: "run-0813-01", bundle: "prod_20260804_v4_r2", evalSet: "dev_v1", n: 800, status: "finished", startedAt: "2026-08-13 08:05", durationMin: 37, precisionPct: 89.2, recallPct: 20.1, gate: "无回退，门禁通过" },
  { id: "run-0812-02", bundle: "prod_20260804_v4_r2", evalSet: "canary_v1", n: 200, status: "finished", startedAt: "2026-08-12 15:47", durationMin: 12, precisionPct: 90.4, recallPct: 21.6, gate: "canary 子集，门禁通过" },
];

/* ============================================================================
   人工审核队列（3 条待审样本）
   ========================================================================== */

export interface ReviewItemSample {
  /** 审核单号 */
  id: string;
  /** 照片编号 */
  photoId: string;
  /** 货架点位 */
  shelf: string;
  /** 候选 SKU（unknown 时无库内匹配） */
  candidate: string;
  /** 置信度 */
  conf: number;
  /** 领先间距 */
  margin: number;
  /** 进审理由 */
  reason: string;
  /** 进入队列时间 */
  arrivedAt: string;
}

export const REVIEW_QUEUE: ReviewItemSample[] = [
  { id: "RV-20260815-014", photoId: "P-0815-03241", shelf: "上海·静安店 A3 层", candidate: "统一 100 老坛酸菜牛肉面 桶装", conf: 0.71, margin: 0.03, reason: "margin 低于阈值 0.05", arrivedAt: "2026-08-15 09:31" },
  { id: "RV-20260815-009", photoId: "P-0815-02187", shelf: "杭州·西湖店 B1 层", candidate: "红牛维生素功能饮料 250ml 罐", conf: 0.58, margin: 0.11, reason: "conf 低于阈值 0.6", arrivedAt: "2026-08-15 08:56" },
  { id: "RV-20260815-003", photoId: "P-0815-01052", shelf: "上海·静安店 C2 层", candidate: "未知（库内无匹配）", conf: 0.66, margin: 0.0, reason: "unknown_review：疑似新品", arrivedAt: "2026-08-15 08:12" },
];

/* ============================================================================
   实验台账（E0 基线 + 两个迭代/推全样本）
   ========================================================================== */

export type ExperimentStage = "baseline" | "iterate" | "promote";

export interface ExperimentSample {
  /** 实验编号 */
  id: string;
  /** 所处阶段 */
  stage: ExperimentStage;
  /** 实验名称 */
  name: string;
  /** 被测识别包 */
  bundle: string;
  /** accepted precision（%） */
  precisionPct: number;
  /** 端到端召回（%） */
  recallPct: number;
  /** review 比例（%） */
  reviewRatioPct: number;
  /** 每张片 FP */
  fpPerPhoto: number;
  /** 备注 */
  note: string;
}

export const EXPERIMENTS: ExperimentSample[] = [
  { id: "E0", stage: "baseline", name: "当前线上基线", bundle: "prod_20260804_v4_r2", precisionPct: 89.0, recallPct: 20.3, reviewRatioPct: 10.5, fpPerPhoto: 3.174, note: "dev_v1 n=800，conf 0.6 / margin 0.05" },
  { id: "E1", stage: "iterate", name: "margin 0.05→0.08 + 难例回灌", bundle: "exp_e1_margin008_r1", precisionPct: 91.2, recallPct: 24.8, reviewRatioPct: 9.8, fpPerPhoto: 2.61, note: "迭代中，待复跑确认" },
  { id: "E2", stage: "promote", name: "检测头重训（hard-negative 增广）", bundle: "exp_e2_hd_r2", precisionPct: 93.4, recallPct: 27.5, reviewRatioPct: 8.9, fpPerPhoto: 2.12, note: "达推全条件，待灰度" },
];
