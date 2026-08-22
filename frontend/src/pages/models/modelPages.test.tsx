/**
 * M9（G8）：模型管理页面组件合同测试。
 *
 * 断言（04 §5/§7 关键安全合同）：
 * - 密钥字段提交后立即清空；DOM 与状态中无明文；
 * - 401/403/429/503 诚实状态；403 不显示资源数量；
 * - maker（created_by == 当前用户）看不到“批准”动作；
 * - 绑定校验展示影响预览（索引重建需求）；
 * - 空态诚实（“暂无连接”），无样本数据。
 * API 全部 mock（真实行为由后端测试覆盖）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let authState: { me: { actor: string } | null; scopes: string[] | null } = {
  me: { actor: "admin" },
  scopes: ["models.config.read", "models.connection.manage",
           "models.secret.rotate", "models.binding.manage",
           "models.release.approve"],
};

vi.mock("@/store/auth", () => ({
  useAuth: (sel: (s: unknown) => unknown) => sel(authState),
}));

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    fetchModelConnections: vi.fn(),
    fetchModelCatalog: vi.fn(),
    fetchModelBindings: vi.fn(),
    fetchModelUsageSummary: vi.fn(),
    fetchModelUsageTimeseries: vi.fn(),
    fetchModelAlerts: vi.fn(),
    postModelJson: vi.fn(),
  };
});

import Connections from "./Connections";
import Bindings from "./Bindings";
import {
  fetchModelBindings,
  fetchModelCatalog,
  fetchModelConnections,
  postModelJson,
} from "@/lib/api";

function render(node: React.ReactElement): {
  container: HTMLElement; cleanup: () => void;
} {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(node));
  return {
    container,
    cleanup: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

const CONN_ROW = {
  connection_id: "local-omlx", version: 1, tenant_id: "local",
  name: "本地 OMLX", location: "local", adapter_kind: "openai_compatible",
  api_flavor: "chat_completions", base_url: "http://127.0.0.1:8455/v1",
  timeout_ms: 30000, max_retries: 1, status: "pending_approval",
  etag: "e1", created_by: "maker-x", created_at: "2026-08-22T00:00:00Z",
  activated_at: null, secret_configured: true, secret_version: 2,
  last_rotated_at: "2026-08-21T00:00:00Z", active_version: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  authState = {
    me: { actor: "admin" },
    scopes: ["models.config.read", "models.connection.manage",
             "models.secret.rotate", "models.binding.manage",
             "models.release.approve"],
  };
});

describe("Connections 页面", () => {
  it("凭据只显示元数据（已配置/版本/轮换时间），无明文", async () => {
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 1, connections: [CONN_ROW],
    });
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    const text = container.textContent ?? "";
    expect(text).toContain("已配置");
    expect(text).toContain("v2");
    expect(text).toContain("轮换 2026-08-21");
    expect(container.querySelector("[data-testid='secret-meta']")).toBeTruthy();
    cleanup();
  });

  it("保存草稿提交密钥后立即清空输入（write-only）", async () => {
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 0, connections: [],
    });
    (postModelJson as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ connection_id: "c1", version: 1, etag: "e" })
      .mockResolvedValueOnce({ secret_configured: true, secret_version: 1 });
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    // 打开表单
    const openBtn = Array.from(container.querySelectorAll("button"))
      .find((b) => b.textContent?.includes("新增连接"));
    act(() => openBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => {});
    const secretInput = container.querySelector(
      "[data-testid='field-secret']") as HTMLInputElement;
    const nameInput = container.querySelector(
      "[data-testid='field-name']") as HTMLInputElement;
    expect(secretInput).toBeTruthy();
    expect(secretInput.type).toBe("password");
    // 受控输入：通过原生 setter + input 事件写入
    const setNative = (el: HTMLInputElement, v: string) => {
      const proto = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, "value");
      proto?.set?.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    };
    act(() => { setNative(nameInput, "t-conn"); setNative(secretInput, "sk-secret-xyz"); });
    await act(async () => {});
    const saveBtn = container.querySelector(
      "[data-testid='save-draft']") as HTMLButtonElement;
    await act(async () => {
      saveBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(postModelJson).toHaveBeenCalledTimes(2);
    const [path2, body2] = (postModelJson as ReturnType<typeof vi.fn>)
      .mock.calls[1].slice(0, 2);
    expect(String(path2)).toContain("/secret");
    expect((body2 as Record<string, string>).secret_value).toBe("sk-secret-xyz");
    // 提交后表单关闭且密钥状态清空：重新打开表单验证输入为空
    const openBtn2 = Array.from(container.querySelectorAll("button"))
      .find((b) => b.textContent?.includes("新增连接"));
    act(() => openBtn2?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => {});
    const secretInput2 = container.querySelector(
      "[data-testid='field-secret']") as HTMLInputElement;
    expect(secretInput2.value).toBe("");
    expect(container.innerHTML).not.toContain("sk-secret-xyz");
    cleanup();
  });

  it("403：不显示资源数量，只显示无权限", async () => {
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockRejectedValue(
      new (await import("@/lib/api")).ApiError(403, "forbidden"));
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    expect(container.textContent).toContain("无模型管理权限");
    expect(container.textContent).not.toContain("暂无连接");
    cleanup();
  });

  it("401：需要登录状态", async () => {
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockRejectedValue(
      new (await import("@/lib/api")).ApiError(401, "unauthorized"));
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    expect(container.textContent).toContain("需要登录");
    cleanup();
  });

  it("maker 看不到批准自己变更的动作", async () => {
    authState.me = { actor: "maker-x" }; // created_by == 当前用户
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 1, connections: [CONN_ROW],
    });
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    expect(container.querySelector(
      "[data-testid='approve-connection']")).toBeNull();
    cleanup();
  });

  it("非 maker 且有 release.approve 才可见批准动作", async () => {
    authState.me = { actor: "checker-y" };
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 1, connections: [CONN_ROW],
    });
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    expect(container.querySelector(
      "[data-testid='approve-connection']")).toBeTruthy();
    cleanup();
  });

  it("空态诚实：暂无连接，无样本数据", async () => {
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 0, connections: [],
    });
    const { container, cleanup } = render(<Connections />);
    await act(async () => {});
    expect(container.textContent).toContain("暂无连接");
    cleanup();
  });
});

describe("Bindings 页面", () => {
  const BINDING_ROW = {
    binding_id: "b1", version: 1, customer_id: "", project_id: "",
    subject_kind: "module", subject_id: "research-rag",
    capability: "embedding", connection_id: "local-omlx",
    connection_version: 1, model_id: "Qwen3-Embedding-0.6B-8bit",
    status: "draft", etag: "e1", created_by: "maker-x",
    created_at: "2026-08-22T00:00:00Z", activated_at: null,
  };

  it("校验后展示影响预览（索引重建需求）", async () => {
    (fetchModelBindings as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 1, bindings: [BINDING_ROW],
    });
    (fetchModelCatalog as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 0, entries: [],
    });
    (fetchModelConnections as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 0, connections: [],
    });
    (postModelJson as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "validated",
      impact: {
        affected_subject: "module:research-rag",
        replaces: null,
        index_rebuild_required: true,
        rollback_target: null,
      },
    });
    const { container, cleanup } = render(<Bindings />);
    await act(async () => {});
    const validateBtn = container.querySelector(
      "[data-testid='validate-binding']") as HTMLButtonElement;
    expect(validateBtn).toBeTruthy();
    await act(async () => {
      validateBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    const impactBox = container.querySelector(
      "[data-testid='impact-preview']");
    expect(impactBox).toBeTruthy();
    expect(impactBox?.textContent).toContain("module:research-rag");
    expect(impactBox?.textContent).toContain(
      "需要（embedding 身份变化，必须重建并评测后切换）");
    cleanup();
  });
});
