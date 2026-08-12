"""N2 Task 11：Recognition Profile（版本化模型链选择）。

红线：识别只允许选择注册的 profile_id，禁止任意权重路径；
单文件/批量/URL/外部 API/内部 Agent 五入口同一契约；
未就绪 profile 可见但禁用并显示 blocker。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

ENTRY_POINTS = ("single_file", "batch", "url", "external_api",
                "internal_agent")

REQUIRED_PROFILES = ("production_legacy", "nextgen_detector",
                     "nextgen_detector_segmenter_classifier",
                     "full_cascade_qwen", "shadow_compare")

_PRODUCTION_BUNDLE = "prod_20260805_v5_r1"
_POLICY_VERSION = "recognition_profile_policy_v1"

_SEED = [
    {"profile_id": "production_legacy",
     "display_name": "当前生产（legacy cascade）",
     "components": {"detector": _PRODUCTION_BUNDLE,
                    "classifier": _PRODUCTION_BUNDLE,
                    "segmenter": None, "vlm": None},
     "status": "enabled", "blockers": []},
    {"profile_id": "nextgen_detector",
     "display_name": "NextGen 检测器",
     "components": {"detector": "candidate_detector_v2",
                    "classifier": _PRODUCTION_BUNDLE,
                    "segmenter": None, "vlm": None},
     "status": "disabled",
     "blockers": ["candidate_detector_v2 未训练/未登记"]},
    {"profile_id": "nextgen_detector_segmenter_classifier",
     "display_name": "NextGen 检测+分割+分类",
     "components": {"detector": "candidate_detector_v2",
                    "classifier": "candidate_classifier_v2",
                    "segmenter": "candidate_segmenter_v2", "vlm": None},
     "status": "disabled",
     "blockers": ["三个 nextgen candidate 均未训练/未登记"]},
    {"profile_id": "full_cascade_qwen",
     "display_name": "完整级联（含 Qwen 裁决）",
     "components": {"detector": "candidate_detector_v2",
                    "classifier": "candidate_classifier_v2",
                    "segmenter": "candidate_segmenter_v2",
                    "vlm": "candidate_vlm_v2"},
     "status": "disabled",
     "blockers": ["candidate_vlm_v2 未训练；MLX 独占资源需排程"]},
    {"profile_id": "shadow_compare",
     "display_name": "Shadow 对比（production vs nextgen）",
     "components": {"detector": "shadow", "classifier": "shadow",
                    "segmenter": None, "vlm": None},
     "status": "disabled",
     "blockers": ["shadow 需至少一个 nextgen candidate 就绪"]},
    # ABOSV3 T8：V4 best 受控切换（用户授权；shadow/回滚验证后启用）
    {"profile_id": "v4_best_standard",
     "display_name": "V4 Best（standard 默认，受控切换）",
     "components": {"detector": "prod_v4_best_r1",
                    "classifier": "prod_v4_best_r1",
                    "segmenter": None, "vlm": None},
     "status": "disabled",
     "blockers": ["待 shadow/回归/回滚验证后由平台 API 切换启用"]},
    # ABOSV3 T8：实验 profile（诚实标注，不伪装 production-ready）
    {"profile_id": "exp_classifier_only",
     "display_name": "实验：仅分类器（不可单独识别原图）",
     "components": {"detector": None,
                    "classifier": "best/classifier_base_9295.pth",
                    "segmenter": None, "vlm": None},
     "status": "disabled",
     "blockers": ["分类器无法单独处理原图：必须与 detector 组合"
                  "（请选择 v4_best_standard 等组合 profile）"]},
    {"profile_id": "exp_nextgen_detector_smoke",
     "display_name": "实验：NextGen detector smoke 制品",
     "components": {"detector": "nextgen_detector_smoke_v1",
                    "classifier": _PRODUCTION_BUNDLE,
                    "segmenter": None, "vlm": None},
     "status": "disabled",
     "blockers": ["smoke 级制品（最小验证用）：指标未达商业门，"
                  "仅限本机实验，不得作商业默认"]},
    {"profile_id": "exp_m3_grouped_classifier",
     "display_name": "实验：M3 grouped 分类器（泄漏重建基线）",
     "components": {"detector": _PRODUCTION_BUNDLE,
                    "classifier": "m3_tvt_e5_v2",
                    "segmenter": None, "vlm": None},
     "status": "disabled",
     "blockers": ["M3 为 grouped 基线（非候选）；真实泛化 30-35%，"
                  "未达商业门，仅实验对照"]},
]


class ProfileError(RuntimeError):
    """Profile 契约错误（fail-closed）。"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self._seed()

    def _seed(self) -> None:
        existing = {r["profile_id"]
                    for r in self.store._conn.execute(
                        "SELECT profile_id FROM recognition_profile_v1"
                    ).fetchall()}
        for p in _SEED:
            if p["profile_id"] in existing:
                continue
            self.store._conn.execute(
                "INSERT INTO recognition_profile_v1 (profile_id,"
                " display_name, components_json, status, blockers_json,"
                " policy_version, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (p["profile_id"], p["display_name"],
                 json.dumps(p["components"], ensure_ascii=False),
                 p["status"],
                 json.dumps(p["blockers"], ensure_ascii=False),
                 _POLICY_VERSION, _utcnow(), _utcnow()))
        self.store._conn.commit()

    def list_profiles(self) -> list[dict[str, Any]]:
        rows = self.store._conn.execute(
            "SELECT * FROM recognition_profile_v1 ORDER BY profile_id"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["components"] = json.loads(d.pop("components_json"))
            d["blockers"] = json.loads(d.pop("blockers_json"))
            out.append(d)
        return out

    def resolve(self, profile_id: str) -> dict[str, Any]:
        if "/" in str(profile_id) or str(profile_id).endswith(".pt"):
            raise ProfileError(
                "禁止任意权重路径：只能选择注册的 recognition_profile_id")
        for p in self.list_profiles():
            if p["profile_id"] == profile_id:
                return {**p, "policy_version": _POLICY_VERSION}
        raise ProfileError(f"未注册 profile: {profile_id}")

    def build_recognition_request(self, *, entry_point: str, source: str,
                                  profile_id: str) -> dict[str, Any]:
        if entry_point not in ENTRY_POINTS:
            raise ProfileError(f"非法入口: {entry_point}")
        p = self.resolve(profile_id)
        if p["status"] != "enabled":
            raise ProfileError(
                f"profile {profile_id} 当前禁用: {p['blockers']}")
        return {"recognition_profile_id": profile_id,
                "entry_point": entry_point, "source": source,
                "components": p["components"],
                "policy_version": p["policy_version"]}


# ---- 纠偏 Task 7：Profile 状态动态派生（不保存过期文本） ----

_PROFILE_DEFS = [
    ("production_legacy", ["prod_20260805_v5_r1_bundle"], [],
     ["production"]),
    ("nextgen_m1_pilot", ["nextgen_detector_pilot_v1"], [], []),
    ("nextgen_m1_merged_suntory", ["nextgen_detector_merged_v2"], [], ["三得利场景候选"]),
    ("nextgen_m1_m2_pilot", ["nextgen_detector_pilot_v1",
                             "nextgen_segmenter_pilot_v1"], [], []),
    ("canonical38_classifier_e1", ["m3_ablation_e1_v1"],
     ["canonical38"], []),
    ("canonical38_classifier_e5", ["m3_ablation_e5_v1"],
     ["canonical38"], []),
    ("canonical38_vlm_real_candidate", ["nextgen_vlm_real_candidate_v1"],
     ["canonical38"], []),
    ("canonical38_cascade", ["nextgen_detector_pilot_v1",
                             "nextgen_segmenter_pilot_v1",
                             "m3_ablation_e5_v1",
                             "nextgen_vlm_real_candidate_v1"],
     ["canonical38"], []),
    ("research83_classifier", ["nextgen_classifier_grouped_v1"],
     ["research83"], ["实验，不可商业输出"]),
    ("research83_full_cascade", ["nextgen_detector_pilot_v1",
                                 "nextgen_segmenter_pilot_v1",
                                 "nextgen_classifier_grouped_v1",
                                 "nextgen_vlm_real_candidate_v1"],
     ["research83"], ["实验，不可商业输出"]),
    ("shadow_compare", ["prod_20260805_v5_r1_bundle",
                        "m3_ablation_e5_v1"], [], ["shadow"]),
]



# ---- 证据链收口（2026-08-10）：artifact 状态纠正表 ----
ARTIFACT_STATUS_FIX = {
    "m3_tvt_e1_v2": "CANDIDATE_PENDING_MICRO_GOLD",
    "m3_tvt_e5_v2": "CANDIDATE_PENDING_MICRO_GOLD",
    "m3_ablation_e1_v1": "EXPERIMENTAL_SUPERSEDED_BY_M3_TVT_E1_V2",
    "m3_ablation_e5_v1": "EXPERIMENTAL_SUPERSEDED_BY_M3_TVT_E5_V2",
}

_PROFILE_SEED = [
    ("production_legacy", ["prod_20260805_v5_r1_bundle"], [], ["production"]),
    ("nextgen_m1_pilot", ["nextgen_detector_pilot_v1"], [], []),
    ("nextgen_m1_merged_suntory", ["nextgen_detector_merged_v2"], [], ["三得利场景候选"]),
    ("nextgen_m1_m2_pilot", ["nextgen_detector_pilot_v1",
                             "nextgen_segmenter_pilot_v1"], [], []),
    ("canonical38_classifier_e1", ["m3_tvt_e1_v2"], ["canonical38"], []),
    ("canonical38_classifier_e5", ["m3_tvt_e5_v2"], ["canonical38"], []),
    ("canonical38_vlm_real_candidate",
     ["nextgen_vlm_real_candidate_v1"], ["canonical38"], []),
    ("canonical38_cascade", ["nextgen_detector_pilot_v1",
                             "nextgen_segmenter_pilot_v1", "m3_tvt_e1_v2",
                             "nextgen_vlm_real_candidate_v1"],
     ["canonical38"], []),
    ("research83_classifier", ["nextgen_classifier_grouped_v1"],
     ["research83"], ["实验，不可商业输出"]),
    ("research83_full_cascade", ["nextgen_detector_pilot_v1",
                                 "nextgen_segmenter_pilot_v1",
                                 "nextgen_classifier_grouped_v1",
                                 "nextgen_vlm_real_candidate_v1"],
     ["research83"], ["实验，不可商业输出"]),
    ("shadow_compare", ["prod_20260805_v5_r1_bundle", "m3_tvt_e1_v2"],
     [], ["shadow"]),
    # ABOSV3 T8：V4 best 受控切换（shadow/回滚验证后由切换服务把制品
    # 置为 CANDIDATE 才启用）；实验 profile 诚实标注，不伪装 production
    ("v4_best_standard", ["prod_v4_best_r1_bundle"], [],
     ["standard 默认，受控切换"]),
    ("exp_classifier_only", ["classifier_base_9295"], [],
     ["实验：分类器不可单独处理原图，必须与 detector 组合"]),
    ("exp_v4_detector_smoke", ["nextgen_detector_smoke_v1"], [],
     ["实验：smoke 级制品，仅限本机验证，不作商业默认"]),
]


def seed_profile_defs(store) -> None:
    import json as _j
    from datetime import datetime, timezone
    for pid, comps, scopes, tags in _PROFILE_SEED:
        if not store._conn.execute(
                "SELECT 1 FROM recognition_profile_def_v1 WHERE"
                " profile_id=?", (pid,)).fetchone():
            store._conn.execute(
                "INSERT INTO recognition_profile_def_v1 (profile_id,"
                " components_json, scopes_json, tags_json, legacy,"
                " created_at) VALUES (?,?,?,?,0,?)",
                (pid, _j.dumps(comps), _j.dumps(scopes), _j.dumps(tags),
                 datetime.now(timezone.utc).isoformat()))
    store._conn.commit()


def derive_profiles(store) -> list[dict]:
    """状态/blocker 从 Artifact Registry 动态派生；定义读 DB（单源）。"""
    import json as _j
    seed_profile_defs(store)
    arts = {r["artifact_id"]: r for r in store._conn.execute(
        "SELECT artifact_id, candidate_status, blocker FROM"
        " model_artifact_registry_v1").fetchall()}
    out = []
    for row in store._conn.execute(
            "SELECT * FROM recognition_profile_def_v1 ORDER BY profile_id"):
        needs = _j.loads(row["components_json"])
        tags = _j.loads(row["tags_json"])
        blockers = []
        if row["profile_id"] != "production_legacy":
            for aid in needs:
                a = arts.get(aid)
                if a is None:
                    blockers.append(f"{aid}: not_registered")
                elif a["candidate_status"] != "CANDIDATE":
                    blockers.append(f"{aid}: {a['candidate_status']}")
            if "nextgen_vlm_real_candidate_v1" in needs:
                ev = store._conn.execute(
                    "SELECT eval_id FROM evaluation_registry_v1 WHERE"
                    " eval_id='m4_three_version_real_eval_v2'").fetchone()
                if ev is None:
                    blockers.append("M4 三版本真实评估未登记")
        out.append({"profile_id": row["profile_id"],
                    "status": "enabled" if not blockers else "disabled",
                    "blockers": blockers, "tags": tags,
                    "components": needs,
                    "scopes": _j.loads(row["scopes_json"])})
    return out
