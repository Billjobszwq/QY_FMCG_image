/**
 * R2-09（Step 2）：Research Workbench 组件测试。
 *
 * 断言（round-2-hardening §10）：
 * - 展示服务端固化 scope、planner degraded、typed 子问题（含依赖/停止条件）、
 *   冲突（命题/取值/来源）、停止规则、citation locator；
 * - 不渲染隐藏推理链（chain-of-thought）。
 * API 全部 mock（真实 API 行为由 tests/research 的后端测试覆盖）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";

// 让 React act() 在 jsdom 测试环境生效
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    status = 500;
  }
  return {
    ApiError,
    fetchResearchStart: vi.fn(),
    fetchResearchStatus: vi.fn(),
    fetchResearchResume: vi.fn(),
    fetchResearchCancel: vi.fn(),
    fetchResearchDecideConflict: vi.fn(),
    fetchResearchClaims: vi.fn(),
    fetchResearchCitations: vi.fn(),
    fetchResearchSynthesize: vi.fn(),
  };
});

import ResearchWorkbench from "./Workbench";
import {
  fetchResearchCitations,
  fetchResearchClaims,
  fetchResearchStart,
  fetchResearchStatus,
  fetchResearchSynthesize,
} from "@/lib/api";

const BASE_RUN = {
  research_run_id: "rrun-1",
  business_run_id: "run-1",
  question: "客户服务响应时限是多少",
  mode: "deep_research",
  status: "succeeded",
  stop_reason: "complete",
  budget: { max_queries: 36, max_iterations: 6 },
  consumed: { queries: 3 },
  tenant_id: "local",
  customer_id: "cust-a",
  project_id: "proj-a",
  data_scope: "operational",
  state: {
    iteration: 1,
    planner_degraded: false,
    stop_rule: "no_new_spans_2_rounds",
    plan: {
      subquestions: [
        { sq_id: "sq-1", text: "子问题一：现行时限", kind: "primary",
          depends_on: [], stop_condition: "找到有效条款" },
        { sq_id: "sq-ce", text: "反证：不同规定", kind: "counterevidence",
          depends_on: ["sq-1"], stop_condition: "找到反例或穷尽来源" },
      ],
    },
    conflicts: [
      { proposition: "客户服务响应时限", unit: "小时", values: [24, 48],
        sources: ["kb-cs-a", "kb-cs-b"] },
    ],
  },
};

function setApi(run: Record<string, unknown>, extra?: Record<string, unknown>) {
  (fetchResearchStart as ReturnType<typeof vi.fn>).mockResolvedValue(run);
  (fetchResearchStatus as ReturnType<typeof vi.fn>).mockResolvedValue(run);
  (fetchResearchClaims as ReturnType<typeof vi.fn>).mockResolvedValue({
    count: 1,
    claims: [{ claim_id: "clm-1", text: "响应时限为 24 小时",
               claim_type: "fact", importance: "high",
               support_status: "supported", confidence: 0.9 }],
  });
  (fetchResearchCitations as ReturnType<typeof vi.fn>).mockResolvedValue({
    gate_ok: true, blocking_claims: [],
    verdicts: [{ claim_id: "clm-1", verdict: "pass", reason: "",
                 valid_spans: ["span-1"] }],
  });
  (fetchResearchSynthesize as ReturnType<typeof vi.fn>).mockResolvedValue({
    report_id: "rep-1", abstain: false,
    claims: [{ claim_id: "clm-1", text: "响应时限为 24 小时",
               claim_type: "fact" }],
    citations: [{ claim_id: "clm-1", span_id: "span-1",
                  relation: "supports" }],
    snapshots: {}, body: {},
    ...(extra ?? {}),
  });
}

async function renderAndStart(run: Record<string, unknown>) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<ResearchWorkbench />);
  });
  const input = container.querySelector("input") as HTMLInputElement;
  const select = container.querySelector("select") as HTMLSelectElement;
  await act(async () => {
    input.value = run.question as string;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    select.value = "deep_research";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  // 触发 React onChange：用原生 setter
  const nativeInputSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    nativeInputSetter?.call(input, run.question as string);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const buttons = Array.from(container.querySelectorAll("button"));
  const startBtn = buttons.find((b) => b.textContent?.includes("启动"));
  await act(async () => {
    startBtn?.click();
  });
  // flush promise microtasks
  await act(async () => {
    await Promise.resolve();
  });
  return { container, root };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ResearchWorkbench", () => {
  it("展示 scope/计划子问题/冲突/停止规则，且不渲染推理链", async () => {
    setApi(BASE_RUN);
    const { container } = await renderAndStart(BASE_RUN);
    const text = container.textContent ?? "";
    // 服务端固化 scope
    expect(text).toContain("cust-a");
    expect(text).toContain("proj-a");
    expect(text).toContain("operational");
    // typed 子问题（依赖 + 停止条件）
    expect(text).toContain("子问题一：现行时限");
    expect(text).toContain("反证：不同规定");
    expect(text).toContain("counterevidence");
    expect(text).toContain("找到有效条款");
    // 冲突（命题/取值/来源）
    expect(text).toContain("客户服务响应时限");
    expect(text).toContain("24 / 48");
    expect(text).toContain("kb-cs-a");
    // 停止规则
    expect(text).toContain("no_new_spans_2_rounds");
    // 不得出现隐藏推理链
    expect(text.toLowerCase()).not.toContain("chain-of-thought");
    expect(container.innerHTML).not.toContain("thinking");
  });

  it("planner 不可用时显示 degraded 提示", async () => {
    const degraded = {
      ...BASE_RUN,
      status: "succeeded",
      stop_reason: "degraded:planner_unavailable",
      state: { ...BASE_RUN.state, planner_degraded: true, plan: undefined,
               conflicts: [] },
    };
    setApi(degraded);
    const { container } = await renderAndStart(degraded);
    expect(container.querySelector('[data-testid="planner-degraded"]'))
      .not.toBeNull();
    expect(container.textContent).toContain("降级");
  });

  it("综合报告展示 citation locator（span 定位）", async () => {
    setApi(BASE_RUN);
    const { container } = await renderAndStart(BASE_RUN);
    const buttons = Array.from(container.querySelectorAll("button"));
    const synBtn = buttons.find((b) =>
      b.textContent?.includes("综合报告"));
    await act(async () => {
      synBtn?.click();
    });
    await act(async () => {
      await Promise.resolve();
    });
    const loc = container.querySelector('[data-testid="citation-locators"]');
    expect(loc).not.toBeNull();
    expect(loc?.textContent).toContain("span-1");
  });
});
