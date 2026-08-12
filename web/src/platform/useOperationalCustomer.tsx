// SI4（指令 8.4/9.2，DEC-SI4-005）：运营客户上下文唯一来源。
// 默认客户必须来自 operational customer Domain Service：
// - 有且仅有一个运营客户 → 自动预选；
// - 无运营客户 → 诚实空态 + 创建/导入入口；
// - 多个运营客户 → 要求人工选择；
// 永不回退 UAT/demo 客户，前端不得硬编码测试客户。
import { useEffect, useState } from "react";
import { iamGet } from "../api";

export interface OperationalCustomer {
  customer_id: string;
  name: string;
}

export function useOperationalCustomer(): {
  customer: string;
  setCustomer: (c: string) => void;
  options: OperationalCustomer[];
} {
  const [options, setOptions] = useState<OperationalCustomer[]>([]);
  const [customer, setCustomer] = useState("");
  useEffect(() => {
    iamGet("master/customers").then((d: any) => {
      const cs: OperationalCustomer[] = d?.customers ?? [];
      setOptions(cs);
      setCustomer((cur) => cur
        || (cs.length === 1 ? cs[0].customer_id : ""));
    }).catch(() => { /* 由页面错误态承接 */ });
  }, []);
  return { customer, setCustomer, options };
}

export function CustomerPicker({ customer, setCustomer, options,
                                 ariaLabel }: {
  customer: string;
  setCustomer: (c: string) => void;
  options: OperationalCustomer[];
  ariaLabel: string;
}) {
  if (!options.length) {
    return (
      <span className="muted" style={{ fontSize: 12 }}>
        暂无运营客户 · 请先在"客户与主数据"创建或经"导入中心"导入
      </span>);
  }
  return (
    <select value={customer} aria-label={ariaLabel}
      onChange={(e) => setCustomer(e.target.value)}>
      {options.length > 1 && <option value="">请选择客户</option>}
      {options.map((c) => (
        <option key={c.customer_id} value={c.customer_id}>
          {c.name}（{c.customer_id}）
        </option>))}
    </select>);
}
