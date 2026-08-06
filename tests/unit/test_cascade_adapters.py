"""VLM-006：FMCG 级联适配器契约测试（全部使用 fake backend，不加载真实模型）。

红线：
- detector 只输出 region，不输出 final SKU 决策；
- ResNet 输出 Top-K / margin / entropy / 模型版本；
- SAM 只输出 mask/crop/证据，不输出 SKU；mask 失败保留原框证据并 needs_review；
- retrieval 返回 registry 内 CandidateSet（闭集外候选过滤）；
- quality 返回 pass/warn/manual_review/reject + 不可变证据引用；
- scene 无模型证据时必须诚实 unknown，不得用文件名/目录名伪造；
- legacy 异常映射为受控 capability error。
"""

from __future__ import annotations

import io
import types

import pytest
from PIL import Image

from src.cascade.cascade_inference import CascadeRecognizer
from src.modules.fmcg.adapters import CapabilityAdapterError
from src.modules.fmcg.adapters.legacy_cascade import LegacyCascadeAdapter
from src.modules.fmcg.adapters.quality import QUALITY_VERDICTS, QualityAdapter
from src.modules.fmcg.adapters.sam_refiner import SamRefinerAdapter
from src.modules.fmcg.adapters.scene import SceneAdapter
from src.modules.fmcg.adapters.sku_retrieval import SkuRetrievalAdapter
from src.modules.fmcg.cascade.contracts import CandidateSet


def _jpeg_bytes(w: int = 64, h: int = 48) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 120, 120)).save(buf, format="JPEG")
    return buf.getvalue()


# ---------- CascadeRecognizer 只读新方法（不触碰 recognize 行为） ----------

class _FakeBoxes:
    def __init__(self, xyxy, cls, conf):
        self._xyxy, self._cls, self._conf = xyxy, cls, conf

    class _T:
        def __init__(self, v):
            self._v = v

        def tolist(self):
            return self._v

    @property
    def xyxy(self):
        return self._T(self._xyxy)

    @property
    def cls(self):
        return self._T(self._cls)

    @property
    def conf(self):
        return self._T(self._conf)


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class _FakeYolo:
    def __init__(self, results):
        self._results = results
        self.names = {}

    def predict(self, *a, **k):
        return self._results


def _bare_recognizer(results) -> CascadeRecognizer:
    """绕过 __init__（避免加载真实权重），只验证新只读方法逻辑。"""
    r = CascadeRecognizer.__new__(CascadeRecognizer)
    r.device = "cpu"
    r.yolo = _FakeYolo(results)
    r.clsid_to_name = {0: "乌龙茶500"}
    r.clsid_to_id = {0: "SKU-WLC-500"}
    return r


def test_detect_regions_outputs_regions_not_final_sku() -> None:
    boxes = _FakeBoxes([[10.0, 5.0, 50.0, 40.0]], [0], [0.88])
    r = _bare_recognizer([_FakeResult(boxes)])
    regions = r.detect_regions(_jpeg_bytes(), conf=0.2)
    assert len(regions) == 1
    reg = regions[0]
    # detector 只输出 region：不得携带最终 SKU 决策字段
    assert "status" not in reg and "sku_id" not in reg
    assert reg["box_px"] == [10.0, 5.0, 50.0, 40.0]
    assert reg["image_width"] == 64 and reg["image_height"] == 48
    assert reg["detector_conf"] == pytest.approx(0.88)
    assert reg["region_id"]


def test_detect_regions_empty_when_no_boxes() -> None:
    r = _bare_recognizer([_FakeResult(None)])
    assert r.detect_regions(_jpeg_bytes()) == []


# ---------- legacy_cascade adapter：异常映射为受控错误 ----------

class _ExplodingRecognizer:
    def detect_regions(self, *a, **k):
        raise RuntimeError("MPS 忙（训练占用）")

    def classify_region(self, *a, **k):
        raise RuntimeError("boom")


def test_legacy_exceptions_mapped_to_capability_error() -> None:
    ad = LegacyCascadeAdapter(_ExplodingRecognizer())
    with pytest.raises(CapabilityAdapterError):
        ad.detect_regions(b"x")
    with pytest.raises(CapabilityAdapterError):
        ad.classify_region(b"x", [0, 0, 1, 1])


def test_legacy_adapter_delegates_and_exposes_model_versions() -> None:
    class FakeRecog:
        model_versions = {"detector": "yolo@v4", "classifier": "resnet18@best"}

        def detect_regions(self, image_bytes, conf=0.25):
            return [{"region_id": "region-000"}]

        def classify_region(self, image_bytes, box, topk=5):
            return {"top1": "SKU-A", "topk": [], "margin": 0.5,
                    "entropy": 0.3, "model_version": "resnet18@best"}

    ad = LegacyCascadeAdapter(FakeRecog())
    assert ad.detect_regions(b"x") == [{"region_id": "region-000"}]
    out = ad.classify_region(b"x", [0, 0, 5, 5])
    # ResNet 输出 Top-K、margin、entropy 和模型版本
    assert out["margin"] == 0.5 and out["entropy"] == 0.3
    assert out["model_version"]
    assert ad.model_versions()["classifier"] == "resnet18@best"


# ---------- quality adapter ----------

def test_quality_adapter_verdicts_and_evidence() -> None:
    def assess(ref):
        return {"verdict": "pass", "scores": {"blur": 0.1}}

    ad = QualityAdapter(assess, rule_version="qpol_v2")
    out = ad.assess({"sha256": "ab" * 32})
    assert out["verdict"] in QUALITY_VERDICTS
    assert out["verdict"] == "pass"
    # 不可变证据引用：原图 SHA + 规则版本
    assert out["evidence"]["sha256"] == "ab" * 32
    assert out["evidence"]["rule_version"] == "qpol_v2"


def test_quality_unknown_verdict_fail_closed_to_manual_review() -> None:
    ad = QualityAdapter(lambda ref: {"verdict": "yolo"}, rule_version="qpol_v2")
    out = ad.assess({"sha256": "cd" * 32})
    assert out["verdict"] == "manual_review"


def test_quality_backend_error_fail_closed_to_manual_review() -> None:
    def boom(ref):
        raise RuntimeError("cv2 崩了")

    ad = QualityAdapter(boom, rule_version="qpol_v2")
    out = ad.assess({"sha256": "ef" * 32})
    assert out["verdict"] == "manual_review"
    assert out["evidence"]["error"]


# ---------- scene adapter：诚实 unknown ----------

def test_scene_without_backend_honest_unknown() -> None:
    ad = SceneAdapter(backend=None)
    # 不得用文件名/目录名伪造场景
    out = ad.classify({"sha256": "aa" * 32, "filename": "货架正面.jpg"})
    assert out["scene"] == "unknown"
    assert out["price_tag"] == "unknown"


def test_scene_backend_vocab_enforced() -> None:
    ad = SceneAdapter(backend=lambda ref: {"scene": "shelf", "price_tag": "present"})
    out = ad.classify({"sha256": "aa" * 32})
    assert out["scene"] == "shelf" and out["price_tag"] == "present"
    # 非法词汇 → 诚实 unknown（fail-closed）
    ad2 = SceneAdapter(backend=lambda ref: {"scene": "超市", "price_tag": "maybe"})
    out2 = ad2.classify({"sha256": "aa" * 32})
    assert out2["scene"] == "unknown" and out2["price_tag"] == "unknown"


# ---------- sam_refiner adapter：只出 mask/crop/证据，不出 SKU ----------

def test_sam_outputs_three_crop_refs_without_sku() -> None:
    def sam(image_ref, box):
        return {"mask_box": [box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1]}

    ad = SamRefinerAdapter(backend=sam)
    out = ad.refine({"sha256": "ab" * 32, "image_width": 100, "image_height": 100},
                    [10.0, 10.0, 50.0, 60.0])
    assert "sku_id" not in out
    crops = out["crops"]
    assert set(crops) == {"coarse", "mask", "context"}
    # 上下文 crop 外扩 10%–20%
    ctx = crops["context"]
    assert ctx[0] < 10.0 and ctx[1] < 10.0 and ctx[2] > 50.0 and ctx[3] > 60.0
    assert out["needs_review"] is False


def test_sam_mask_failure_keeps_coarse_and_needs_review() -> None:
    def bad_sam(image_ref, box):
        raise RuntimeError("SAM mask 失败")

    ad = SamRefinerAdapter(backend=bad_sam)
    out = ad.refine({"sha256": "ab" * 32, "image_width": 100, "image_height": 100},
                    [10.0, 10.0, 50.0, 60.0])
    assert out["needs_review"] is True
    assert out["crops"]["mask"] is None  # 不伪造 mask
    assert out["crops"]["coarse"] == [10.0, 10.0, 50.0, 60.0]
    assert out["failure_reason"]


def test_sam_without_backend_honest_needs_review() -> None:
    ad = SamRefinerAdapter(backend=None)
    out = ad.refine({"sha256": "ab" * 32, "image_width": 10, "image_height": 10},
                    [1.0, 1.0, 5.0, 5.0])
    assert out["needs_review"] is True and out["crops"]["mask"] is None


# ---------- sku_retrieval adapter：闭集候选 ----------

def test_retrieval_returns_candidateset_within_registry() -> None:
    def backend(region):
        return [("SKU-A", 0.9), ("SKU-EVIL", 0.8), ("SKU-B", 0.7)]

    ad = SkuRetrievalAdapter(
        registry_ids={"SKU-A", "SKU-B"},
        backend=backend,
        registry_version="reg-2026-08",
        retrieval_version="retrieval.v1",
    )
    cs = ad.retrieve(region_id="region-000", limit=8)
    assert isinstance(cs, CandidateSet)
    ids = [c.sku_id for c in cs.candidates]
    assert ids == ["SKU-A", "SKU-B"]  # 闭集外候选被过滤
    assert cs.registry_version == "reg-2026-08"


def test_retrieval_empty_registry_fail_closed() -> None:
    ad = SkuRetrievalAdapter(registry_ids=set(), backend=lambda r: [],
                             registry_version="reg-x")
    with pytest.raises(CapabilityAdapterError):
        ad.retrieve(region_id="region-000")


def test_retrieval_without_backend_fail_closed() -> None:
    ad = SkuRetrievalAdapter(registry_ids={"SKU-A"}, backend=None,
                             registry_version="reg-x")
    with pytest.raises(CapabilityAdapterError):
        ad.retrieve(region_id="region-000")
