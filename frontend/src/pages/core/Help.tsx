/**
 * 帮助中心（P1 core/Help）—— runbook 要点静态排版。
 *
 * 内容摘要自 docs/runbook.md（启动方式 / 运行手册）：
 * —— 受支持架构为级联链路（:8300/:8301/:8304/:8091/:8092），
 *    legacy 8090/8091 旧链路只用于历史回归，禁止生产使用；
 * —— 服务清单 / TL;DR / 常驻服务与守护 / 测试 / 故障排查 / 只读验证 /
 *    当前状态与待办。
 *
 * 数据红线：静态内容为 runbook 摘要（文档而非业务数据）；
 * 「导入模板说明」为唯一实时数据块，走同源 /api/v1/import/templates。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fetchIamGet } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HedgehogMascot } from "@/components/ui/mascot";
import {
  ApiTable,
  PageHeader,
  StatusBadge,
} from "@/components/data";
import type { ApiTableCol, StatusKind } from "@/components/data";
import { cn } from "@/lib/utils";

/* ============================================================================
   静态内容（runbook 摘要）
   ========================================================================== */

/** 卡片壳：细边框小圆角，标题行 + 内容区。 */
function Card({
  title,
  aside,
  children,
  className,
}: {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-md border border-border bg-background", className)}>
      {title && (
        <header className="flex items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
          <h3 className="font-display text-[13px] font-bold text-text-primary">
            {title}
          </h3>
          {aside}
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}

/** 命令 / 代码行：等宽小字 + 面板底。 */
function CodeLine({ children }: { children: string }) {
  return (
    <code className="block rounded border border-border/60 bg-surface px-2 py-1 font-mono text-xs text-text-primary">
      {children}
    </code>
  );
}

interface ServiceRow {
  name: string;
  port: string;
  tier: "生产" | "legacy";
  note: string;
}

const SERVICES: ServiceRow[] = [
  { name: "Label Studio 标注/审核", port: ":8300", tier: "生产", note: "正式标注入口（assisted / blind 双项目）" },
  { name: "ML 后端自动标注", port: ":8301", tier: "生产", note: "级联自动提案" },
  { name: "编排 API", port: ":8304", tier: "生产", note: "级联链路编排" },
  { name: "识别服务（级联 /v2）", port: ":8091", tier: "生产", note: "src.recognize.service；legacy /v1 仅回归" },
  { name: "统一监控（看门狗守护）", port: ":8092", tier: "生产", note: "monitor_watchdog.sh 每 10 秒探活拉起" },
  { name: "新版前端（vite preview）", port: ":4173", tier: "生产", note: "静态 dist 服务，挂了重起即可" },
  { name: "人工审核（legacy）", port: ":8090", tier: "legacy", note: "只用于历史回归，禁止生产使用" },
];

const SERVICE_COLS: ApiTableCol<ServiceRow>[] = [
  { key: "name", label: "服务" },
  { key: "port", label: "端口" },
  {
    key: "tier",
    label: "定位",
    render: (r) => (
      <StatusBadge kind={r.tier === "生产" ? "good" : "neutral"}>
        {r.tier}
      </StatusBadge>
    ),
  },
  { key: "note", label: "备注" },
];

/** legacy smoke 全流程 TL;DR（仅历史回归）。 */
const TLDR_STEPS: { cmd: string; desc: string }[] = [
  { cmd: "python -m src.catalog.build_kb", desc: "建知识库 → .kb（内容哈希去重，VLM 结构化卡 + 1024d 向量）" },
  { cmd: "python -m src.field.photos", desc: "入库实景 → .field（只读解析，OSS 直链下载，manifest + blobs）" },
  { cmd: "warehouse.migrate(connect())", desc: "初始化仓库（8 表 + 触发器，幂等可重复执行）" },
  { cmd: "python -m src.labeling.runner --mode B", desc: "自动提案：只写 proposals/，不写训练源；按不确定度入审核队列" },
  { cmd: "python -m src.labeling.review_server --port 8090", desc: "人工审核（人工门）：仅 approved 生成训练源，事件留痕" },
  { cmd: "python -m src.eval.label_eval", desc: "标注质量评测：覆盖率 / 标签一致率 / 不一致复核队列" },
  { cmd: "python -m src.training.dataset", desc: "构数据集 → .datasets/v1（按照片切分防泄漏）" },
  { cmd: "python -m src.training.trainer", desc: "smoke 训练：yolo11n 微调 1 epoch（CPU 可跑，证明链路）" },
  { cmd: "python -m src.recognize.api --port 8091", desc: "起识别接口（每次调用追加 recognition_run 审计）" },
  { cmd: "python -m src.eval.recog_eval", desc: "识别质量评测：检测召回 + 识别准确（在检出的框上）" },
];

interface TroubleRow {
  id: string;
  symptom: string;
  fix: string;
}

const TROUBLES: TroubleRow[] = [
  { id: "vlm", symptom: "VLM / OCR / 嵌入全报错", fix: "omlx 未起或模型未加载；跑 setup 第 5 节校验" },
  { id: "readonly", symptom: "REFUSE WRITE into read-only source", fix: "正常——你在试图写只读原始资产，别写" },
  { id: "oss", symptom: "实景入库 OSS 失败", fix: "确认能访问 bucket-spar.oss-cn-shanghai.aliyuncs.com" },
  { id: "docker", symptom: "docker compose up 拉镜像超时", fix: "配国内镜像源或 pre-pull + retag；或干脆用原生路径" },
  { id: "noimages", symptom: "训练 no images/labels", fix: "approved/ 为空——先在人工审核 approved 至少一张" },
  { id: "nobottle", symptom: "识别接口检测不到瓶", fix: "通用检测器对密集小瓶召回有限；训练饮料专用检测器后改善" },
];

const TROUBLE_COLS: ApiTableCol<TroubleRow>[] = [
  { key: "symptom", label: "现象" },
  { key: "fix", label: "处理" },
];

/** 当前状态与待办（runbook 末尾快照）。 */
const STATE_ITEMS: { kind: StatusKind; label: string; text: string }[] = [
  { kind: "good", label: "已建成", text: "Label Studio 标注/审核（:8300）、ML 后端自动标注（:8301）、编排 API（:8304）、识别 dashboard、统一监控（:8092）" },
  { kind: "good", label: "已冻结", text: "YOLO 检测器冻结于 sku_v4（mAP50=0.6887）作画框器" },
  { kind: "neutral", label: "已停止", text: "级联分类器当前训练已停止；生产 checkpoint 为 208 类 ResNet18，val_acc 83.67% @ ep10，不含 __unknown__" },
  { kind: "warn", label: "需注意", text: "2026-08-04 复核时实际监听的只有 8091 识别与 8092 监控；8300 / 8301 / 8304 未运行——不能把“代码存在”写成“在线联调完成”" },
  { kind: "warn", label: "下一步", text: "不是直接续训：先从未训练新门店冻结 gold-v2，跑检测真实框上限和 GT-crop classifier oracle，再决定 detector / 裁剪数据 / classifier 路线" },
];

/** 角色手册要点（摘自 web HelpDocs 的操作手册文案）。 */
interface DocEntry {
  id: string;
  title: string;
  role: string;
  body: string;
}

const DOCS: DocEntry[] = [
  { id: "first-login", title: "首次登录与冷启动", role: "所有角色", body: "使用管理员分配的账号登录。登录后进入首页总控台：今日待办、日历、项目进度、实时活动、系统容量、Agent 提醒、快速目标与最近对象。" },
  { id: "import", title: "导入客户/项目/SKU/地址/角色", role: "平台管理员", body: "导入中心提供 CSV/XLSX 模板；上传后先 dry-run（逐行新增/跳过/冲突/错误），修复错误后提交（按自然键幂等，证据与审计留痕）。" },
  { id: "survey", title: "从空白创建问卷", role: "项目管理员", body: "问卷中心：从空白新建 → 题型库添加 → 属性面板配置必填/选项/分值/维度/照片 → 跳题逻辑 → lint → 发布 → 分配填写。已发布不可原地修改，修改走新版本。" },
  { id: "geo", title: "地址导入、坐标与地图", role: "项目管理员", body: "位置与外勤：导入或新增地址后获取坐标（Provider）；未配置 Provider 时按提示设置，或手工/导入经纬度确认（不伪造坐标）。无瓦片时诚实降级。" },
  { id: "recognition", title: "识别：五入口与 Profile", role: "客户管理员", body: "单图/批量/URL/API/Agent 五入口共用任务台账。默认 standard profile 受控切换、可回滚；实验 profile 诚实标注 blocker。结果含框/SKU/置信度/耗时/证据/用量。" },
  { id: "training", title: "标注、数据集与自主训练", role: "平台管理员", body: "Label Studio 为正式标注入口（assisted 显示建议，blind 不泄漏预测）；数据集支持照片池/筛选/快照；训练四 Lane 支持 preflight / dry-run / 批准 / 队列 / 发布计划。本轮不做长训练。" },
  { id: "bi", title: "BI：指标、公式与看板", role: "分析师", body: "分析报告：注册制指标 + 受限公式 DSL（禁任意 SQL）；图表原语呈现柱状/折线/数字卡；点击数字下钻到事实行；异常 → 追问 → 回答 → 报表刷新新版本。" },
  { id: "workflow", title: "工作流运行与模板", role: "平台管理员", body: "工作流与 Agent：模板草稿 → lint → 模拟 → 人工批准 → 发布 → 测试运行。wait 为持久化 timer，重启可恢复。运行中心统一看待办/批准/重试。" },
  { id: "agent", title: "Agent 配置与对话", role: "平台管理员", body: "Agent 矩阵：版本化定义（Soul/Prompt/工具 allowlist/预算/审批）；draft → 发布 → 回滚；health 为有界探针；写动作需人工批准。" },
  { id: "iam", title: "账号、角色与权限", role: "平台管理员", body: "账号与权限：开设用户/服务账号/Agent 身份；自定义角色（权限只从已注册 bundle 组合）；授权到客户/项目作用域；最后一个平台管理员不可删除。" },
  { id: "usage", title: "客户 Usage 与账单", role: "财务", body: "财务与结算：按客户/项目/单位统计用量（storage/photo/model_compute/token/agent）；账单仅来自不可变 Usage，调整 append-only，结算后不可改。" },
  { id: "troubleshoot", title: "故障排查", role: "所有角色", body: "页面打不开先看本页「故障排查」与「系统状态」；403 多为作用域隔离（非故障）；Agent 降级属诚实行为（LLM 未配置）。详见 docs/runbook.md。" },
];

/** 导入模板（实时来自 Import Center；管理员接口，失败诚实降级）。 */
interface ImportTemplate {
  template_id: string;
  name: string;
  idempotency: string;
  columns: unknown[];
  note?: string;
}

const TEMPLATE_COLS: ApiTableCol<ImportTemplate>[] = [
  {
    key: "name",
    label: "模板",
    render: (t) => (
      <div>
        <div className="text-text-primary">{t.name}</div>
        <div className="text-xs text-text-secondary">{t.template_id}</div>
      </div>
    ),
  },
  { key: "idempotency", label: "幂等键" },
  {
    key: "columns",
    label: "字段数",
    align: "right",
    render: (t) => String(t.columns?.length ?? 0),
  },
  { key: "note", label: "备注", render: (t) => t.note || "CSV/XLSX 双格式" },
];

/* ============================================================================
   页面
   ========================================================================== */

export default function Help() {
  const [q, setQ] = useState("");

  const [templates, setTemplates] = useState<ImportTemplate[] | null>(null);
  const [tplErr, setTplErr] = useState<unknown>(null);
  const [tplLoading, setTplLoading] = useState(true);

  const loadTemplates = useCallback(async () => {
    setTplLoading(true);
    setTplErr(null);
    try {
      const d = (await fetchIamGet("import/templates")) as {
        templates?: ImportTemplate[];
      };
      setTemplates(d.templates ?? []);
    } catch (e) {
      setTemplates(null);
      setTplErr(e);
    } finally {
      setTplLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const kw = q.trim().toLowerCase();
  const hit = (...fields: string[]) =>
    !kw || fields.some((f) => f.toLowerCase().includes(kw));

  // 列表条目按关键词过滤（数据量小，直接内联计算）
  const services = SERVICES.filter((s) => hit(s.name, s.port, s.note));
  const troubles = TROUBLES.filter((t) => hit(t.symptom, t.fix));
  const docs = DOCS.filter((d) => hit(d.title, d.role, d.body));
  const steps = TLDR_STEPS.filter((s) => hit(s.cmd, s.desc));
  const stateItems = STATE_ITEMS.filter((s) => hit(s.label, s.text));

  // 命令/说明类卡片的命中判定（与列表条目一起参与“无匹配”计算）
  const startupHit = hit("级联", "legacy", "setup", "omlx", ".env", "启动", "前提");
  const residentHit = hit(
    "看门狗", "watchdog", "vite preview", "4173", "8092",
    "pytest", "nohup", "监控", "前端", "测试", "守护",
  );
  const readonlyHit = hit(
    "bundle", "verify", "v2/health", "只读", "写操作", "验证", "复核",
  );

  const nothing =
    !startupHit &&
    !residentHit &&
    !readonlyHit &&
    services.length === 0 &&
    troubles.length === 0 &&
    docs.length === 0 &&
    steps.length === 0 &&
    stateItems.length === 0;

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="帮助中心"
        desc="runbook 要点：启动方式 / 服务清单 / 故障排查 / 只读验证（摘要自 docs/runbook.md）"
        aside={
          <Button variant="secondary" size="sm" asChild>
            <a href="/api/v1/docs" target="_blank" rel="noreferrer">
              API Explorer（OpenAPI）
            </a>
          </Button>
        }
      />

      {/* 全文搜索：过滤本页全部静态条目 */}
      <Input
        value={q}
        aria-label="帮助搜索"
        placeholder="搜索：如 导入 / 标注 / 坐标 / 回滚 / 看门狗…"
        onChange={(e) => setQ(e.target.value)}
        className="max-w-md"
      />

      {nothing && (
        <Card>
          <div className="flex flex-col items-center gap-1.5 py-4">
            <HedgehogMascot className="h-16 w-auto" />
            <p className="text-xs text-text-secondary">
              无匹配结果；试试其他关键词或查看 docs/runbook.md
            </p>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {/* 启动要点 */}
        {startupHit && (
          <Card title="启动要点">
            <ul className="list-disc space-y-1 pl-4 text-[13px] text-text-primary">
              <li>
                前提：已按 docs/setup.md 装好依赖、起好 omlx、配好 .env；
                所有命令在项目根目录执行。
              </li>
              <li>
                当前受支持架构为级联链路（:8300/:8301/:8304/:8091/:8092），
                唯一服务清单见 docs/services.json。
              </li>
              <li>
                TL;DR 与 8090/8091 旧链路为 legacy，只用于历史回归验证，
                禁止生产使用；新成员直接按「服务清单」启动。
              </li>
            </ul>
          </Card>
        )}

        {/* 服务清单 */}
        {services.length > 0 && (
          <Card title="服务清单（docs/services.json 为准）">
            <ApiTable<ServiceRow>
              rows={services}
              cols={SERVICE_COLS}
              rowKey={(r) => r.port}
              emptyText="无匹配的服务"
            />
          </Card>
        )}

        {/* legacy 全流程 TL;DR */}
        {steps.length > 0 && (
          <Card
            title="全流程 TL;DR（legacy smoke 链路）"
            aside={<StatusBadge kind="neutral">仅历史回归</StatusBadge>}
            className="xl:col-span-2"
          >
            <ol className="space-y-1">
              {steps.map((s, i) => (
                <li key={s.cmd} className="grid grid-cols-[20px_1fr] gap-x-2">
                  <span className="text-xs text-text-secondary tabular-nums">
                    {i + 1}
                  </span>
                  <div className="min-w-0">
                    <CodeLine>{s.cmd}</CodeLine>
                    <p className="mt-0.5 text-xs text-text-secondary">{s.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        )}

        {/* 常驻服务与守护 */}
        {residentHit && (
          <Card title="常驻服务与守护">
          <div className="space-y-2.5 text-[13px] text-text-primary">
            <div>
              <p className="mb-1 text-xs text-text-secondary">
                监控服务（:8092）由看门狗每 10 秒探活并自动拉起；不要同时用多个入口重复拉起 monitor。
              </p>
              <CodeLine>nohup bash scripts/monitor_watchdog.sh &gt;/dev/null 2&gt;&amp;1 &amp; disown</CodeLine>
              <div className="mt-1 space-y-1">
                <CodeLine>ps aux | grep [m]onitor_watchdog</CodeLine>
                <CodeLine>tail .models/monitor_watchdog.log</CodeLine>
              </div>
            </div>
            <div>
              <p className="mb-1 text-xs text-text-secondary">
                新版前端（:4173）以 vite preview 服务构建产物，静态服务挂了重起即可。
              </p>
              <CodeLine>npm --prefix frontend install &amp;&amp; npm --prefix frontend run build</CodeLine>
              <div className="mt-1">
                <CodeLine>nohup npm --prefix frontend run preview -- --port 4173 --strictPort --host 127.0.0.1 &gt;.models/frontend_preview.log 2&gt;&amp;1 &amp; disown</CodeLine>
              </div>
            </div>
            <div>
              <p className="mb-1 text-xs text-text-secondary">
                测试（不变性 / 对齐 / 命名 / 别名等契约）：
              </p>
              <CodeLine>python -m pytest tests/unit tests/contract -q</CodeLine>
            </div>
          </div>
          </Card>
        )}

        {/* 只读验证命令 */}
        {readonlyHit && (
          <Card title="当前只读验证命令">
            <div className="space-y-1">
              <CodeLine>python -m src.models.bundle current</CodeLine>
              <CodeLine>python -m src.models.bundle verify --bundle-id prod_20260804_v4_r2</CodeLine>
              <CodeLine>curl -s http://127.0.0.1:8091/v2/health</CodeLine>
              <CodeLine>python -m pytest tests/ -q</CodeLine>
            </div>
            <p className="mt-2 text-xs text-text-secondary">
              端口 / 命令以 docs/services.json 为准。训练、数据重建、发布和服务重启都是写操作，
              不属于只读复核；执行前应先取得负责人确认并创建不可变数据/实验版本。
            </p>
          </Card>
        )}

        {/* 故障排查 */}
        {troubles.length > 0 && (
          <Card title="故障排查" className="xl:col-span-2">
            <ApiTable<TroubleRow>
              rows={troubles}
              cols={TROUBLE_COLS}
              rowKey={(r) => r.id}
              emptyText="无匹配的故障条目"
            />
          </Card>
        )}

        {/* 当前状态与待办 */}
        {stateItems.length > 0 && (
          <Card title="当前状态与待办（runbook 快照）" className="xl:col-span-2">
            <ul className="space-y-1.5">
              {stateItems.map((s) => (
                <li key={s.label} className="flex items-start gap-2">
                  <StatusBadge kind={s.kind} className="mt-0.5 shrink-0">
                    {s.label}
                  </StatusBadge>
                  <span className="text-[13px] text-text-primary">{s.text}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 border-t border-border/60 pt-2 text-xs text-text-secondary">
              完整状态快照见 docs/handbook.md；严格二次复核见
              docs/latest-handbook-reverification-2026-08-04.md。
            </p>
          </Card>
        )}
      </div>

      {/* 角色手册要点 */}
      {docs.length > 0 && (
        <section className="space-y-2">
          <h2 className="font-display text-sm font-bold text-text-primary">
            角色手册要点
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {docs.map((d) => (
              <Card key={d.id}>
                <h4 className="font-display text-[13px] font-bold text-text-primary">
                  {d.title}
                </h4>
                <p className="mt-0.5 text-xs text-text-secondary">适用：{d.role}</p>
                <p className="mt-1.5 text-[13px] leading-relaxed text-text-primary">
                  {d.body}
                </p>
              </Card>
            ))}
          </div>
        </section>
      )}

      {/* 导入模板说明（唯一实时数据块） */}
      <section className="space-y-2">
        <h2 className="font-display text-sm font-bold text-text-primary">
          导入模板说明（实时来自导入中心）
        </h2>
        <ApiTable<ImportTemplate>
          rows={templates ?? []}
          cols={TEMPLATE_COLS}
          loading={tplLoading}
          error={tplErr}
          onRetry={() => void loadTemplates()}
          emptyText="暂无导入模板（或当前账号无管理员权限）"
          rowKey={(t) => t.template_id}
        />
      </section>
    </div>
  );
}
