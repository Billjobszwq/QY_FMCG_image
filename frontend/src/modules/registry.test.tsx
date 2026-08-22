/**
 * M5（G4）：模块导航投影测试——模型管理是受限独立模块。
 *
 * 合同（04 §6）：
 * - 普通员工（无 models scope）：visibleGroups 不含 models；
 * - 至少命中一个 required scope 才渲染 models 组；
 * - scopes 缺失/加载失败（null/undefined）→ fail-closed 隐藏受限模块；
 * - 智能识别不再包含 /vision/models；旧路由经别名映射到 /models/local。
 */
import { describe, expect, it } from "vitest";

import {
  MODULE_GROUPS,
  ROUTE_ALIASES,
  visibleGroups,
} from "./registry";

describe("模型管理导航投影", () => {
  it("普通员工（无 models scope）看不到模型管理", () => {
    const employeeScopes = ["vision.read", "master.read", "home.read"];
    expect(
      visibleGroups(employeeScopes).some((g) => g.group === "models"),
    ).toBe(false);
  });

  it("命中任一 required scope 即显示模型管理组", () => {
    expect(visibleGroups(["models.config.read"])).toContainEqual(
      expect.objectContaining({ group: "models" }),
    );
    expect(visibleGroups(["models.usage.read"])).toContainEqual(
      expect.objectContaining({ group: "models" }),
    );
  });

  it("scopes 缺失时受限模块 fail-closed 隐藏", () => {
    expect(visibleGroups(null).some((g) => g.group === "models")).toBe(false);
    expect(visibleGroups(undefined).some((g) => g.group === "models")).toBe(
      false,
    );
    // 无权限限制的模块不受影响
    expect(visibleGroups(null).some((g) => g.group === "core")).toBe(true);
  });

  it("模型管理固定五个页签且顺序稳定", () => {
    const models = MODULE_GROUPS.find((g) => g.group === "models");
    expect(models).toBeTruthy();
    expect(models!.items.map((i) => i.route)).toEqual([
      "/models/connections",
      "/models/catalog",
      "/models/bindings",
      "/models/governance",
      "/models/local",
    ]);
  });

  it("智能识别不再包含系统级模型管理标签", () => {
    const vision = MODULE_GROUPS.find((g) => g.group === "vision");
    expect(vision).toBeTruthy();
    expect(vision!.items.map((i) => i.route)).not.toContain("/vision/models");
  });

  it("旧 /vision/models 经别名映射到 /models/local（兼容期不删除）", () => {
    expect(ROUTE_ALIASES["/vision/models"]).toBe("/models/local");
  });

  it("财务仅 usage read 也可见（只看运行治理数据，后端仍独立鉴权）", () => {
    expect(visibleGroups(["models.usage.read"])).toContainEqual(
      expect.objectContaining({ group: "models" }),
    );
  });
});
