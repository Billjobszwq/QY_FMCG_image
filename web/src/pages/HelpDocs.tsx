// ABOSV3 T11：帮助与文档（全员可见；全文搜索；角色/任务手册；
// 导入模板说明实时来自 Import Center；API Explorer 入口；故障排查）。
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { iamGet } from "../api";
import { PageHeader } from "../platform/components";

interface DocEntry { id: string; title: string; role: string;
  body: string; to?: string; }

const DOCS: DocEntry[] = [
  { id: "first-login", title: "首次登录与冷启动", role: "所有角色",
    body: "使用管理员分配的账号登录（本机：./bin/abos start 启动 8091/8092/8300/8400 后访问 8400）。登录后进入首页总控台：今日待办、日历、项目进度、实时活动、系统容量、Agent 提醒、快速目标与最近对象。",
    to: "/home" },
  { id: "import", title: "导入客户/项目/SKU/地址/角色（Import Center）",
    role: "平台管理员",
    body: "数据与资产 → Import Center：14 套 CSV/XLSX 模板可下载；上传后先 dry-run（逐行新增/跳过/冲突/错误），修复错误后提交（按自然键幂等，证据与审计留痕）。模板第一页含字段类型/必填/枚举/样例说明。",
    to: "/data/import" },
  { id: "survey", title: "从空白创建问卷", role: "项目管理员",
    body: "调研与问卷 → 问卷设计器：从空白新建 → 题型库添加（单选/多选/填空/数字/日期/打分/矩阵/拍照/说明）→ 属性面板配置必填/选项/分值/维度/照片（门头必拍/自拍可选/质量门/识别建议）→ 跳题逻辑 → lint → 发布 → 分配填写。已发布不可原地修改，修改走新版本。",
    to: "/survey/design" },
  { id: "geo", title: "地址导入、坐标与地图", role: "项目管理员",
    body: "位置与外勤 → 地址与地理编码：导入或新增地址后点“获取坐标（Provider）”；未配置 Provider 时按提示设置 GEOCODER_PROVIDER 与 Key，或手工/导入经纬度确认（不伪造坐标）。地图面板展示点位/围栏/路线/未分配任务；无瓦片时诚实降级为散点示意。",
    to: "/geo/addresses" },
  { id: "recognition", title: "识别：五入口与 Profile", role: "客户管理员",
    body: "智能识别：单图/批量/URL/API/Agent 五入口共用任务台账。默认 standard profile 为 V4 best（受控切换，可回滚）；实验 profile 诚实标注 blocker，不伪装 production。结果含框/SKU/置信度/耗时/证据/用量。",
    to: "/vision/recognize" },
  { id: "training", title: "标注、数据集与自主训练", role: "平台管理员",
    body: "Label Studio 为正式标注入口（assisted 显示建议，blind 不泄漏预测）；数据集页面支持照片池/筛选/快照；训练中心四 Lane（detector/YOLO-seg/classifier/VLM）支持 preflight/dry-run/批准/队列/日志/制品/评估/发布计划。本轮不做长训练。",
    to: "/vision/models" },
  { id: "bi", title: "BI：指标、公式与看板", role: "分析师",
    body: "分析与 BI → BI 工作台：注册制指标 + 受限公式 DSL（禁任意 SQL）；ECharts 画布添加柱状/折线/饼图/数字卡；点击数字下钻到事实行；异常 → 追问 → 回答 → 报表刷新新版本。",
    to: "/analytics/reports" },
  { id: "workflow", title: "可视化工作流", role: "平台管理员",
    body: "工作流与 Agent → 工作流搭建：React Flow 画布拖拽节点（触发/条件/转换/循环/并行/汇合/等待/人工批准/Agent/模型/命令/子流程）→ lint → 模拟 → 人工批准 → 发布 → 测试运行。JSON 仅作高级视图。wait 为持久化 timer，重启可恢复。",
    to: "/workflow/studio" },
  { id: "agent", title: "Agent 配置与对话", role: "平台管理员",
    body: "工作流与 Agent → Agent 中心：版本化定义（Soul/Prompt/工具 allowlist/预算/审批）；draft→发布→回滚；health 为有界探针；主管对话走真实工具循环，写动作需人工批准。",
    to: "/workflow/agents" },
  { id: "iam", title: "账号、角色与权限", role: "平台管理员",
    body: "账号与权限：开设用户/服务账号/Agent 身份；自定义角色（权限只从已注册 bundle 组合）；授权到客户/项目作用域；权限模拟器回答“能否/为什么”；最后一个平台管理员不可删除。",
    to: "/iam/accounts" },
  { id: "usage", title: "客户 Usage 与账单", role: "财务",
    body: "财务与结算：客户 Usage 工作台按客户/项目/单位统计（storage/photo/model_compute/token/agent）；每行下钻 run/证据；趋势/异常/未归属/CSV 导出；账单仅来自不可变 Usage，调整 append-only，结算后不可改。",
    to: "/finance/contracts" },
  { id: "troubleshoot", title: "故障排查", role: "所有角色",
    body: "页面打不开 → ./bin/abos status/start；识别 unreachable → 8091 重启；403 → 作用域隔离（非故障）；Agent 降级 → 属诚实行为（LLM 未配置）；DB 报错 → ./bin/abos doctor（迁移幂等）。详见 docs/OPERATOR-RUNBOOK.md。" },
];

export default function HelpDocs() {
  const [q, setQ] = useState("");
  const [templates, setTemplates] = useState<any[]>([]);
  useEffect(() => {
    iamGet("import/templates").then(
      (d) => setTemplates(d.templates)).catch(() => { });
  }, []);
  const hits = useMemo(() => {
    const kw = q.trim().toLowerCase();
    if (!kw) return DOCS;
    return DOCS.filter((d) =>
      (d.title + d.body + d.role).toLowerCase().includes(kw));
  }, [q]);
  return (
    <>
      <PageHeader title="帮助与文档"
        desc="按角色/任务组织的操作手册 · 导入模板说明 · API Explorer · 故障排查（全文搜索）" />
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input style={{ flex: 1, minWidth: 220 }}
            placeholder="搜索：如 导入 / 问卷 / 坐标 / 回滚…"
            aria-label="帮助搜索" value={q}
            onChange={(e) => setQ(e.target.value)} />
          <a className="btn" href="/api/v1/docs" target="_blank"
            rel="noreferrer">API Explorer（OpenAPI）</a>
          <Link className="btn" to="/status">系统状态（管理员）</Link>
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns:
        "repeat(auto-fit, minmax(320px, 1fr))" }}>
        {hits.map((d) => (
          <div className="card" key={d.id} style={{ marginBottom: 0 }}>
            <h3>{d.title}</h3>
            <p className="v meta">适用：{d.role}</p>
            <p className="v" style={{ fontSize: 13 }}>{d.body}</p>
            {d.to && <Link to={d.to}>前往 →</Link>}
          </div>))}
        {hits.length === 0 && (
          <div className="card"><p className="v">
            无匹配结果；试试其他关键词或查看
            docs/USER-HANDBOOK.md</p></div>)}
      </div>
      <div className="card">
        <h3>导入模板说明（实时来自 Import Center）</h3>
        <table className="table">
          <thead><tr><th>模板</th><th>幂等键</th><th>字段数</th><th>备注
          </th></tr></thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.template_id}>
                <td data-label="模板">{t.name}
                  <div className="meta">{t.template_id}</div></td>
                <td data-label="幂等键" className="v">
                  {t.idempotency}</td>
                <td data-label="字段数">{t.columns.length}</td>
                <td data-label="备注" className="v">
                  {t.note || "CSV/XLSX 双格式"}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
    </>
  );
}
