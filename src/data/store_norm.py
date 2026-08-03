"""门店名规范化与模糊别名归一（G2/G4 门禁基础）。

背景（final-training-execution-gate G4）：`_norm_store` 旧实现只做
trim/casefold，dev_v1 有 2 个经 Unicode/中英文括号统一后才与 batch2
重叠的门店别名（何惠晴（上海如海） vs 何惠晴(上海如海)、
陈娟（承照便利店) vs 陈娟(承照便利店)）。所有协议冻结、训练抽样
排除和泄漏检查必须统一使用本模块的 canonical key。

规范化步骤（顺序固定，任何调用方不得自行变体）：
  1. Unicode NFKC（全角字母/数字/符号 → 半角）
  2. 中文括号/方括号/标点 → 半角等价
  3. 全部空白删除（门店名中空白不承载语义）
  4. casefold（比 lower 更严格的 Unicode 大小写折叠）
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

# 标点统一表：全角/中文 → 半角等价
_PUNCT_MAP = {
    ord("（"): "(", ord("）"): ")",
    ord("【"): "[", ord("】"): "]",
    ord("「"): "[", ord("」"): "]",
    ord("《"): "[", ord("》"): "]",
    ord("．"): ".", ord("。"): ".",
    ord("，"): ",", ord("、"): ",",
    ord("！"): "!", ord("？"): "?",
    ord("："): ":", ord("；"): ";",
    ord("－"): "-", ord("—"): "-", ord("–"): "-",
    ord("　"): "",  # 全角空格直接删除
}

# 模糊别名表（canonical → canonical 的显式合并，追加制）。
# 当前为空：规范标点/空白/casefold 已能覆盖已知 2 个重叠案例；
# 若后续发现词面不同但实为同一门店（更名/别名），追加在此并在
# build audit 中披露。
ALIAS_TABLE: dict[str, str] = {}


def norm_store(name) -> str:
    """返回门店名的 canonical key。相同门店的任何写法必须收敛到同一 key。"""
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = s.translate(_PUNCT_MAP)
    s = re.sub(r"\s+", "", s)
    s = s.casefold()
    return ALIAS_TABLE.get(s, s)


def store_of_filename(filename: str) -> str:
    """batch3 文件名第 2 段为门店名：`连锁_门店_类型_时间戳_采集人_n.jpg`。"""
    parts = str(filename).split("_")
    return parts[1] if len(parts) > 1 else "NA"


def session_of_filename(filename: str) -> str:
    """采集会话键 = canonical 门店 + 采集日期（时间戳段前 8 位 yyyymmdd）。

    同门店同日期的整组照片视为一次采集会话；协议集按门店整组分配，
    会话隔离在门店隔离成立时自动成立，此键用于显式审计。"""
    parts = str(filename).split("_")
    store = norm_store(parts[1]) if len(parts) > 1 else "na"
    ts = parts[3] if len(parts) > 3 else ""
    date = ts[:8] if ts[:8].isdigit() else "nodate"
    return f"{store}@{date}"


def load_alias_table(path: Path | None = None) -> dict:
    """可选外部别名表（data/sku_store_aliases.json），合并进 ALIAS_TABLE。"""
    global ALIAS_TABLE
    p = path
    if p is None:
        from ..common.config import PROJECT_ROOT
        p = PROJECT_ROOT / "data" / "store_aliases.json"
    if p and Path(p).exists():
        extra = json.loads(Path(p).read_text(encoding="utf-8"))
        ALIAS_TABLE.update({norm_store(k): norm_store(v) for k, v in extra.items()})
    return ALIAS_TABLE
