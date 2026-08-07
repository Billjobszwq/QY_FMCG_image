"""生成 Label Studio 208 类 SKU 标注配置。

从 data/sku_registry.json 读取全部 SKU，生成 configs/label-studio/label_config.xml。
结构：Image(缩放/旋转) + RectangleLabels(商品框) + perRegion Taxonomy(208 SKU 可搜索)
      + perRegion status(裁决状态，含 unreviewed 初始态) + perRegion TextArea(留痕备注)。
状态语义：unreviewed = 自动 prediction 初始态，不得进入 human_final；
matched 只能由人工选择。
用法：python -m src.ls_platform.gen_label_config"""
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

from ..common.config import PROJECT_ROOT

REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
OUT = PROJECT_ROOT / "configs" / "label-studio" / "label_config.xml"


def build_config(registry: dict) -> str:
    # 按 class_id 排序，保证与 YOLO 类别一致
    names = sorted(registry.keys(), key=lambda n: registry[n]["class_id"])

    # 用 Taxonomy 承载 208 个 SKU（可搜索、可滚动，远优于 208 个内联 Choice）
    sku_choices = "\n".join(
        f'        <Choice value="{escape(n)}" />' for n in names
    )

    xml = f"""<View>
  <Header value="SKU 检测标注与审核：绘制/修正商品框，选择 SKU，标记裁决状态" />
  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="true" crosshair="true" maxWidth="100%" />
  <RectangleLabels name="box" toName="image" strokeWidth="2">
    <Label value="product" background="#1f77b4" />
  </RectangleLabels>
  <Taxonomy name="sku" toName="image" perRegion="true" required="false"
            placeholder="选择 SKU（可搜索）" maxWidth="100%">
{sku_choices}
  </Taxonomy>
  <Choices name="status" toName="image" perRegion="true" required="true"
           header="裁决状态" choice="single-radio" showInLine="true">
    <Choice value="unreviewed" alias="unreviewed" />
    <Choice value="matched" alias="matched" />
    <Choice value="unknown" alias="unknown" />
    <Choice value="conflict" alias="conflict" />
    <Choice value="unreadable" alias="unreadable" />
  </Choices>
  <TextArea name="note" toName="image" perRegion="true" editable="true" rows="1"
            placeholder="冲突/不可判定原因（可选，留痕用）" />
</View>
"""
    return xml


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    xml = build_config(registry)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(xml, encoding="utf-8")
    print(f"已生成 {OUT}")
    print(f"  SKU 类别数: {len(registry)}")
    print(f"  文件大小: {OUT.stat().st_size} bytes")
    return OUT


if __name__ == "__main__":
    main()
