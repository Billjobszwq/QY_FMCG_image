/**
 * 标注协同（/vision/annotation，v3 瘦版）。
 *
 * 数据源（真实接口，无样本数据）：
 *   GET  /api/v1/labeling/inbox                     webhook inbox 事件计数
 *   GET  /api/v1/labeling/batches                   标注批次（assisted/blind 双项目）
 *   POST /api/v1/labeling/batches                   新建双项目批次（真实 mutation）
 *   POST /api/v1/labeling/batches/{id}/import       导入照片并写预标注（风险操作：
 *                                                   触发真实识别，可能数十秒，UI 保留并标注）
 *   GET  /api/v1/labeling/batches/{id}/reconcile    对账报告（LS 为事实源）
 *   GET  /api/v1/review/status                      审核队列统计与分批扩展计划
 *   GET  /api/v1/review/tasks                       审核任务明细（需登录）
 *   POST /api/v1/review/claim · /api/v1/review/submit · /api/v1/review/export
 *
 * 红线回显：blind 项目绝不写 prediction；SAM 预测永远不是最终标注；
 * final_box 只来自人工；队列追加式不可变。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchClaimReviewTask,
  fetchCreateLabelingBatch,
  fetchExportReview,
  fetchLabelingBatches,
  fetchLabelingInbox,
  fetchLabelingReconcile,
  fetchImportLabelingFiles,
  fetchReviewStatus,
  fetchReviewTasks,
  fetchSubmitReview,
  type LabelingBatch,
  type ReconcileReport,
  type ReviewTaskRow,
} from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  errorMessageOf,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  type StatusKind,
} from "@/components/data";
import { StatTile } from "@/components/charts/primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   业务语言映射
   ========================================================================== */

const REVIEW_STATUS_CN: Record<string, string> = {
  pending: "待认领",
  claimed: "已认领待审",
  awaiting_second: "等待第二审",
  awaiting_arbitration: "分歧待仲裁",
  finalized: "已终态",
};

function reviewStatusKind(status: string): StatusKind {
  switch (status) {
    case "finalized":
      return "good";
    case "awaiting_second":
    case "awaiting_arbitration":
      return "warn";
    default:
      return "neutral";
  }
}

/** 分批扩展计划状态（禁止伪造通过）。 */
const BP_CN: Record<string, string> = {
  waiting_human: "等待人工（禁止伪造通过）",
  gate_failed: "批次质量不达标，已停止扩展",
  ready: "可扩展现有阶梯",
  done: "全部阶梯完成",
  empty: "队列为空",
};

/** Label Studio 本机入口（8300）。 */
const LS_BASE = "http://127.0.0.1:8300";

/* ============================================================================
   页面主体
   ========================================================================== */

export default function Annotation() {
  /* ---- labeling：inbox / 批次 / 对账 ---- */
  const [batches, setBatches] = useState<LabelingBatch[] | null>(null);
  const [inbox, setInbox] = useState<number | null>(null);
  const [labelingErr, setLabelingErr] = useState<unknown>(null);
  const [reconcile, setReconcile] = useState<ReconcileReport | null>(null);
  const [name, setName] = useState("");
  const [targetBatch, setTargetBatch] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  /* ---- review：状态统计 / 任务明细 ---- */
  const [reviewStatus, setReviewStatus] = useState<Awaited<
    ReturnType<typeof fetchReviewStatus>
  > | null>(null);
  const [reviewTasks, setReviewTasks] = useState<ReviewTaskRow[] | null>(null);
  const [reviewNeedLogin, setReviewNeedLogin] = useState(false);
  const [reviewErr, setReviewErr] = useState<unknown>(null);
  const [boxInputs, setBoxInputs] = useState<Record<string, string>>({});

  /* ---- 通用反馈 ---- */
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  /** 打开登录窗口（窗口管理器幂等）。 */
  const openWindow = useWindowManager((s) => s.openWindow);
  const closeWindow = useWindowManager((s) => s.closeWindow);
  const openLogin = useCallback(() => {
    openWindow({
      id: "login",
      title: "平台登录",
      content: <LoginWindow onLoggedIn={() => closeWindow("login")} />,
      defaultPosition: { x: 320, y: 180 },
      defaultSize: { width: 360, height: 420 },
    });
  }, [openWindow, closeWindow]);

  /* ---- 加载：labeling（inbox + 批次） ---- */
  const loadLabeling = useCallback(async () => {
    setLabelingErr(null);
    try {
      const [b, i] = await Promise.all([fetchLabelingBatches(), fetchLabelingInbox()]);
      setBatches(b.batches);
      setInbox(i.count);
    } catch (e) {
      setLabelingErr(e);
    }
  }, []);

  /* ---- 加载：review（状态统计 + 任务明细；明细 401 → 需要登录） ---- */
  const loadReview = useCallback(async () => {
    setReviewErr(null);
    setReviewNeedLogin(false);
    try {
      const s = await fetchReviewStatus();
      setReviewStatus(s);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setReviewNeedLogin(true);
      else setReviewErr(e);
    }
    try {
      const t = await fetchReviewTasks();
      setReviewTasks(t.tasks);
    } catch (e) {
      setReviewTasks(null);
      if (e instanceof ApiError && e.status === 401) setReviewNeedLogin(true);
      else if (!(e instanceof ApiError && e.status === 401)) setReviewErr(e);
    }
  }, []);

  const reload = useCallback(async () => {
    await Promise.all([loadLabeling(), loadReview()]);
  }, [loadLabeling, loadReview]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /* ---- mutations ---- */

  const onCreate = async () => {
    if (!name.trim()) return;
    setBusy("创建双项目批次中…");
    setMsg(null);
    try {
      const out = await fetchCreateLabelingBatch(name.trim());
      setName("");
      setTargetBatch(out.batch.batch_id);
      await loadLabeling();
      setMsg(`已创建批次 ${out.batch.name}（assisted/blind 双项目）`);
    } catch (e) {
      setMsg(`创建失败：${errorMessageOf(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const onImport = async () => {
    const files = Array.from(fileRef.current?.files ?? []);
    if (!targetBatch || files.length === 0) return;
    setBusy(`导入 ${files.length} 张（真实识别预标注，可能需要数十秒）…`);
    setMsg(null);
    try {
      const report = await fetchImportLabelingFiles(targetBatch, files);
      if (fileRef.current) fileRef.current.value = "";
      await loadLabeling();
      setReconcile(await fetchLabelingReconcile(targetBatch));
      setMsg(
        `导入完成：assisted ${JSON.stringify(report["assisted"])} / blind ${JSON.stringify(
          report["blind"],
        )} / predictions_written=${String(report["predictions_written"])}`,
      );
    } catch (e) {
      setMsg(`导入失败：${errorMessageOf(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const onReconcile = async (batchId: string) => {
    setBusy("对账中…");
    setMsg(null);
    try {
      setReconcile(await fetchLabelingReconcile(batchId));
    } catch (e) {
      setMsg(`对账失败：${errorMessageOf(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const onClaim = async (t: ReviewTaskRow) => {
    setMsg(null);
    try {
      const r = await fetchClaimReviewTask(t.claim_token);
      setMsg(r.claimed ? `已认领 ${t.task_id}` : "该任务已被认领");
      await loadReview();
    } catch (e) {
      setMsg(`认领失败：${errorMessageOf(e)}`);
    }
  };

  const onSubmit = async (t: ReviewTaskRow, verdict: string, role = "annotator") => {
    const raw = boxInputs[t.task_id] ?? "";
    const box = raw.split(/[,，\s]+/).filter(Boolean).map(Number);
    if (box.length !== 4 || box.some((v) => !Number.isFinite(v))) {
      setMsg("请先填写合法框：x1,y1,x2,y2");
      return;
    }
    setMsg(null);
    try {
      const r = await fetchSubmitReview(t.task_id, verdict, box, role);
      setMsg(r.finalized ? `${t.task_id} 已终态` : `${t.task_id}：${String(r.status)}`);
      await loadReview();
    } catch (e) {
      setMsg(`提交失败：${errorMessageOf(e)}`);
    }
  };

  const onExport = async () => {
    setMsg(null);
    try {
      const r = await fetchExportReview();
      setMsg(`导出完成：${r.n_finalized}/${r.n_tasks} 终态，SHA ${r.sha256.slice(0, 12)}…`);
    } catch (e) {
      setMsg(`导出失败：${errorMessageOf(e)}`);
    }
  };

  const d = reviewStatus?.status_distribution ?? {};
  const bp = reviewStatus?.batch_plan;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="标注协同"
        desc="Label Studio 双项目批次、webhook inbox 与审核队列闭环（认领/双审/仲裁）"
        aside={
          <Button variant="secondary" size="sm" onClick={() => void reload()} disabled={busy !== null}>
            刷新
          </Button>
        }
      />

      {/* 概览：审核队列计数（真实计数，不硬编码） */}
      {reviewNeedLogin ? (
        <NeedLoginState onOpenLogin={openLogin} />
      ) : reviewErr !== null ? (
        <ErrorState message={errorMessageOf(reviewErr)} onRetry={() => void loadReview()} />
      ) : reviewStatus !== null ? (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
            <StatTile label="队列总数" value={reviewStatus.n_tasks} />
            <StatTile label="待认领" value={d.pending ?? 0} />
            <StatTile label="审核中" value={(d.claimed ?? 0) + (d.awaiting_second ?? 0)} />
            <StatTile label="待仲裁" value={d.awaiting_arbitration ?? 0} />
            <StatTile label="已终态" value={d.finalized ?? 0} note="final_box 只来自人工" />
            <StatTile
              label="webhook inbox"
              value={inbox ?? "—"}
              note="按 (source, event_id) 去重"
            />
          </div>
          {bp && (
            <p className="text-xs text-text-secondary">
              分批扩展（100→500→2000→全 eligible）：当前批次 {bp.stage ?? "—"}，状态{" "}
              {BP_CN[bp.status] ?? bp.status}
              {typeof bp.n_total === "number" && `，进度 ${bp.n_finalized ?? 0}/${bp.n_total}`}
              {bp.next_size != null && `，下一批 ${bp.next_size === -1 ? "全 eligible" : bp.next_size}`}
              。任何批次质量不达标立即停止。
            </p>
          )}
        </>
      ) : null}

      {/* 标注批次（labeling/batches + labeling/inbox） */}
      <section className="space-y-2 rounded-md border border-border bg-surface p-3">
        <header className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-medium text-text-primary">标注批次（assisted / blind 双项目）</h2>
          <p className="text-xs text-text-secondary">
            辅助标注显示自动方框与建议 SKU；盲审抽检 0 prediction 是正确设计，不是失败
          </p>
        </header>
        {labelingErr !== null ? (
          <ErrorState message={errorMessageOf(labelingErr)} onRetry={() => void loadLabeling()} />
        ) : (
          <ApiTable<LabelingBatch>
            rows={batches ?? []}
            loading={batches === null}
            emptyText="暂无批次。创建双项目批次并导入照片开始标注"
            rowKey={(b) => b.batch_id}
            cols={[
              { key: "name", label: "批次" },
              { key: "batch_id", label: "batch_id", render: (b) => `${b.batch_id.slice(0, 8)}…` },
              {
                key: "assisted",
                label: "assisted",
                render: (b) =>
                  b.assisted_project_id !== null ? (
                    <a
                      href={`${LS_BASE}/projects/${b.assisted_project_id}/data`}
                      target="_blank"
                      rel="noreferrer"
                      title="主人工标注入口：自动方框 + 建议 SKU"
                      className="accent-interactive text-[13px] text-text-primary"
                    >
                      #{b.assisted_project_id} 进入辅助标注
                    </a>
                  ) : (
                    <span className="text-text-secondary">—</span>
                  ),
              },
              {
                key: "blind",
                label: "blind",
                render: (b) =>
                  b.blind_project_id !== null ? (
                    <a
                      href={`${LS_BASE}/projects/${b.blind_project_id}`}
                      target="_blank"
                      rel="noreferrer"
                      title="盲审不显示任何模型 prediction，仅供被指派人员进入"
                      className="accent-interactive text-[13px] text-text-primary"
                    >
                      #{b.blind_project_id} 盲审抽检
                    </a>
                  ) : (
                    <span className="text-text-secondary">—</span>
                  ),
              },
              { key: "task_count", label: "任务数", align: "right" },
              {
                key: "status",
                label: "状态",
                render: (b) => (
                  <StatusBadge
                    kind={b.status === "reconciled" || b.status === "closed" ? "good" : "neutral"}
                  >
                    {b.status}
                  </StatusBadge>
                ),
              },
              {
                key: "op",
                label: "操作",
                render: (b) => (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2"
                    disabled={busy !== null}
                    onClick={() => void onReconcile(b.batch_id)}
                  >
                    对账
                  </Button>
                ),
              },
            ]}
          />
        )}

        {/* 对账报告（LS 为事实源，不一致显式标记） */}
        {reconcile && (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-xs font-medium text-text-secondary">
                对账报告 {reconcile.batch_id.slice(0, 8)}…
              </h3>
              <StatusBadge kind={reconcile.consistent ? "good" : "serious"}>
                {reconcile.consistent ? "consistent" : "inconsistent（显式标记，不谎报）"}
              </StatusBadge>
              <StatusBadge kind={reconcile.blind_no_predictions ? "good" : "serious"}>
                blind_no_predictions={String(reconcile.blind_no_predictions)}
              </StatusBadge>
            </div>
            <ApiTable
              rows={(["assisted", "blind"] as const).map((k) => {
                const p = reconcile.projects[k];
                return {
                  project: k,
                  tasks: p.tasks,
                  annotations: p.annotations_api,
                  predictions: p.predictions_api,
                  inbox_events: p.inbox_events,
                  inbox_annotation_events: p.inbox_annotation_events,
                  consistent: p.consistent,
                };
              })}
              rowKey={(r) => r.project}
              cols={[
                { key: "project", label: "项目" },
                { key: "tasks", label: "tasks", align: "right" },
                { key: "annotations", label: "标注(API)", align: "right" },
                { key: "predictions", label: "预标注(API)", align: "right" },
                { key: "inbox_events", label: "inbox 事件", align: "right" },
                { key: "inbox_annotation_events", label: "inbox 标注事件", align: "right" },
                {
                  key: "consistent",
                  label: "一致",
                  render: (r) => (
                    <StatusBadge kind={r.consistent ? "good" : "serious"}>
                      {String(r.consistent)}
                    </StatusBadge>
                  ),
                },
              ]}
            />
          </div>
        )}

        {/* 新建批次 / 导入照片（真实 mutation） */}
        <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-2">
          <Input
            className="w-40"
            placeholder="批次名（如 trial10）"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="批次名"
          />
          <Button size="sm" variant="secondary" disabled={busy !== null || !name.trim()} onClick={() => void onCreate()}>
            创建双项目批次
          </Button>
          <Select
            aria-label="目标批次"
            className="w-44"
            value={targetBatch}
            onChange={(e) => setTargetBatch(e.target.value)}
          >
            <option value="">选择目标批次…</option>
            {(batches ?? []).map((b) => (
              <option key={b.batch_id} value={b.batch_id}>
                {b.name}（{b.batch_id.slice(0, 8)}…）
              </option>
            ))}
          </Select>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept="image/*"
            aria-label="导入照片"
            className="max-w-52 text-xs text-text-secondary file:mr-2 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-surface file:px-2 file:py-1 file:text-xs file:text-text-primary"
          />
          <Button size="sm" variant="secondary" disabled={busy !== null || !targetBatch} onClick={() => void onImport()}>
            导入并写预标注
          </Button>
        </div>
        <p className="text-xs text-text-secondary">
          注意：导入会触发真实识别预标注（可能数十秒）；blind 项目绝不写入
          prediction。人工标注/双审/仲裁需授权后进行；平台不自动启动任何训练。
        </p>
      </section>

      {/* 审核队列（review/tasks） */}
      <section className="space-y-2 rounded-md border border-border bg-surface p-3">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-text-primary">审核任务明细</h2>
          {reviewTasks !== null && !reviewNeedLogin && (
            <Button size="sm" variant="secondary" onClick={() => void onExport()}>
              不可变导出（admin）
            </Button>
          )}
        </header>
        {reviewNeedLogin ? (
          <NeedLoginState onOpenLogin={openLogin} />
        ) : (
          <>
            <p className="text-xs text-text-secondary">
              SAM 预测永远不是最终标注；未完成任务不得伪造完成；队列与事件追加式不可变。
            </p>
            <ApiTable<ReviewTaskRow>
              rows={(reviewTasks ?? []).slice(0, 100)}
              loading={reviewTasks === null && reviewErr === null}
              error={reviewErr}
              onRetry={() => void loadReview()}
              emptyText="审核队列为空"
              rowKey={(t) => t.task_id}
              cols={[
                { key: "photo_id", label: "photo" },
                {
                  key: "review_mode",
                  label: "模式",
                  render: (t) => (t.review_mode === "blind_review" ? "单审（盲抽）" : "双审"),
                },
                {
                  key: "status",
                  label: "状态",
                  render: (t) => (
                    <StatusBadge kind={reviewStatusKind(t.status)}>
                      {REVIEW_STATUS_CN[t.status] ?? t.status}
                    </StatusBadge>
                  ),
                },
                { key: "claimed_by", label: "认领人" },
                {
                  key: "final_box",
                  label: "final box",
                  render: (t) =>
                    t.final_box ? t.final_box.join(",") : <span className="text-text-secondary">—</span>,
                },
                {
                  key: "box_input",
                  label: "审核框 x1,y1,x2,y2",
                  render: (t) =>
                    t.status === "finalized" ? (
                      <span className="text-text-secondary">不可改</span>
                    ) : (
                      <Input
                        className="h-7 w-36 text-xs"
                        placeholder="x1,y1,x2,y2"
                        value={boxInputs[t.task_id] ?? ""}
                        onChange={(e) =>
                          setBoxInputs({ ...boxInputs, [t.task_id]: e.target.value })
                        }
                        aria-label={`审核框 ${t.task_id}`}
                      />
                    ),
                },
                {
                  key: "op",
                  label: "操作",
                  render: (t) => (
                    <span className="flex items-center gap-1">
                      {t.status === "pending" && (
                        <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => void onClaim(t)}>
                          认领
                        </Button>
                      )}
                      {t.status !== "finalized" && (
                        <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => void onSubmit(t, "accepted")}>
                          提交框
                        </Button>
                      )}
                      {t.status === "awaiting_arbitration" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2"
                          onClick={() => void onSubmit(t, "adjudicated", "arbiter")}
                        >
                          仲裁
                        </Button>
                      )}
                    </span>
                  ),
                },
              ]}
            />
          </>
        )}
      </section>

      {/* 操作反馈 */}
      {busy && <p className="text-xs text-text-secondary">{busy}</p>}
      {msg && <p className="text-xs text-text-secondary">{msg}</p>}
    </div>
  );
}
