import { describe, expect, it } from "vitest";
import { clamp, cn } from "./utils";

describe("clamp", () => {
  it("区间内原样返回", () => {
    expect(clamp(5, 0, 10)).toBe(5);
  });
  it("低于下限取下限", () => {
    expect(clamp(-3, 0, 10)).toBe(0);
  });
  it("高于上限取上限", () => {
    expect(clamp(42, 0, 10)).toBe(10);
  });
});

describe("cn", () => {
  it("合并类名并让后值覆盖前值", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-text-primary", undefined)).toBe("text-text-primary");
  });
});
