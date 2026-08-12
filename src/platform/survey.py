"""ABOSV2 Phase E：问卷域服务层（03-DOMAIN-PACKS-SPEC §3）。

- 题型：single_choice / multi_choice / text / rating / photo（首批）；
  矩阵/排序/地址/签名等预留类型不伪造实现（lint 报错）；
- 版本：发布后不可原地修改；修改生成新版本，历史 Response 绑定原版本；
- 跳题：可验证 DAG（检测循环、不可达、冲突条件、缺失默认分支）；
- 评分：规则版本化，输出公式版本 + 输入答案 + 计算证据；
- 后台修正：correction event（原值/新值/原因/操作者/批准人）+ 评分
  重算版本；禁止直接 UPDATE 语义（只经 correction 通道）；
- 拍照题：位置/时间/设备/质量证据；识别结果只是 suggestion，
  人工 accept/reject/modify 后才成为 final answer；拒绝/修改反馈
  进入评估链且 training_truth=false（不得自动成为训练真值）。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

QUESTION_TYPES = ("single_choice", "multi_choice", "text", "rating",
                  "photo", "matrix", "description")

# UATCC T1：照片拍摄角色（门头/货架/自拍/商品/其他不得混淆）
CAPTURE_ROLES = ("storefront", "shelf", "employee_selfie", "product",
                 "other")


class SurveyError(Exception):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# 含全部首批题型的样板问卷模板（G5 验收基线）
TEMPLATE_STORE_VISIT = {
    "template_id": "tpl_store_visit_v1",
    "name": "门店巡检样板问卷（全首批题型）",
    "spec": {
        "sections": [{"id": "s1", "title": "门店基础"},
                     {"id": "s2", "title": "陈列与拍照"}],
        "questions": [
            {"id": "q_store_type", "section": "s1",
             "type": "single_choice", "title": "门店类型",
             "options": [{"value": "convenience", "label": "便利店"},
                         {"value": "supermarket", "label": "超市"},
                         {"value": "other", "label": "其他"}]},
            {"id": "q_sku_present", "section": "s1", "type": "multi_choice",
             "title": "本店在售我们的哪些系列（可多选，引用 SKU 库）",
             "options": [{"value": "SKU-OLD", "label": "旧包装系列",
                          "sku_ref": True},
                         {"value": "SKU-NEW", "label": "新包装系列",
                          "sku_ref": True}],
             "required": True},
            {"id": "q_shelf_len", "section": "s1", "type": "text",
             "title": "货架长度（米）", "input_type": "number"},
            {"id": "q_score_service", "section": "s2", "type": "rating",
             "title": "店员服务评分", "min": 1, "max": 5},
            {"id": "q_storefront_photo", "section": "s2", "type": "photo",
             "title": "门头照（必拍，capture_role=storefront）",
             "min_count": 1, "max_count": 3, "required": True,
             "require_storefront": True, "capture_role": "storefront",
             "recognition": False,
             "quality": {"min_width": 320}},
            {"id": "q_shelf_photo", "section": "s2", "type": "photo",
             "title": "货架拍照（识别建议需人工确认）",
             "min_count": 1, "max_count": 5,
             "require_storefront": False, "capture_role": "shelf",
             "selfie_optional": True, "recognition": True,
             "manual_confirmation_required": True,
             "quality": {"min_width": 320}},
        ],
        "logic_edges": [
            {"from": "q_store_type",
             "when": {"op": "eq", "value": "other"},
             "to": "END_SKIP_S2",
             "note": "其他类型门店跳过 s2 陈列检查（示例分支）"},
        ],
        "scoring": {
            "version": 1,
            "rules": [
                {"question": "q_store_type",
                 "map": {"convenience": 5, "supermarket": 4, "other": 2}},
                {"question": "q_score_service", "weight": 2},
            ],
            "formula": "sum",
        },
    },
}
TEMPLATES = [TEMPLATE_STORE_VISIT]


class SurveyService:
    def __init__(self, store: Any, gateway: Any = None) -> None:
        self.store = store
        self.gateway = gateway

    # ---------- 定义与生命周期 ----------

    def create_draft(self, *, name: str, spec: dict | None = None,
                     actor: str, from_template: str | None = None,
                     survey_id: str | None = None) -> dict:
        if from_template:
            tpl = next((t for t in TEMPLATES
                        if t["template_id"] == from_template), None)
            if tpl is None:
                raise SurveyError(f"模板不存在: {from_template}")
            spec = json.loads(json.dumps(tpl["spec"]))
            name = name or tpl["name"]
        if not name or not isinstance(spec, dict):
            raise SurveyError("name/spec 必填")
        sid = survey_id or "svy-" + uuid.uuid4().hex[:10]
        if self._get(sid) is not None:
            raise SurveyError(f"survey 已存在: {sid}（请用新版本）")
        now = _now()
        spec_json = json.dumps(spec, sort_keys=True, ensure_ascii=False)
        self.store._conn.execute(
            "INSERT INTO survey_definition_v1 (survey_id, version, name,"
            " status, spec_json, spec_hash, created_by, created_at,"
            " updated_at) VALUES (?,?,?, ?,?,?,?,?,?)",
            (sid, 1, name, "draft", spec_json,
             hashlib.sha256(spec_json.encode()).hexdigest(), actor,
             now, now))
        self.store._conn.commit()
        return self.get_survey(sid)

    def _get(self, survey_id: str, version: int | None = None) -> dict | None:
        if version is None:
            row = self.store._conn.execute(
                "SELECT * FROM survey_definition_v1 WHERE survey_id=?"
                " ORDER BY version DESC LIMIT 1", (survey_id,)).fetchone()
        else:
            row = self.store._conn.execute(
                "SELECT * FROM survey_definition_v1 WHERE survey_id=? AND"
                " version=?", (survey_id, version)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["spec"] = json.loads(d["spec_json"])
        d["lint_report"] = json.loads(d["lint_report_json"] or "[]")
        return d

    def get_survey(self, survey_id: str,
                   version: int | None = None) -> dict:
        d = self._get(survey_id, version)
        if d is None:
            raise SurveyError(f"survey 不存在: {survey_id}")
        return d

    def list_surveys(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM survey_definition_v1"
            " ORDER BY survey_id, version").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["spec"] = json.loads(d["spec_json"])
            d["lint_report"] = json.loads(d["lint_report_json"] or "[]")
            out.append(d)
        return out

    def update_draft(self, survey_id: str, *, spec: dict | None = None,
                     name: str | None = None) -> dict:
        d = self.get_survey(survey_id)
        if d["status"] != "draft":
            raise SurveyError(
                f"已发布问卷不可原地修改（当前 {d['status']}）；"
                "请生成新版本")
        sets, vals = [], []
        if spec is not None:
            spec_json = json.dumps(spec, sort_keys=True, ensure_ascii=False)
            sets += ["spec_json=?", "spec_hash=?"]
            vals += [spec_json,
                     hashlib.sha256(spec_json.encode()).hexdigest()]
        if name is not None:
            sets.append("name=?"); vals.append(name)
        sets.append("updated_at=?"); vals.append(_now())
        self.store._conn.execute(
            f"UPDATE survey_definition_v1 SET {', '.join(sets)}"
            " WHERE survey_id=? AND version=?",
            (*vals, survey_id, d["version"]))
        self.store._conn.commit()
        return self.get_survey(survey_id)

    def new_version(self, survey_id: str, *, actor: str) -> dict:
        latest = self.get_survey(survey_id)
        now = _now()
        self.store._conn.execute(
            "INSERT INTO survey_definition_v1 (survey_id, version, name,"
            " status, spec_json, spec_hash, created_by, created_at,"
            " updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (survey_id, latest["version"] + 1, latest["name"], "draft",
             latest["spec_json"], latest["spec_hash"], actor, now, now))
        self.store._conn.commit()
        return self.get_survey(survey_id, latest["version"] + 1)

    # ---------- lint：跳题 DAG 校验 ----------

    def lint(self, survey_id: str) -> dict:
        d = self.get_survey(survey_id)
        report = self.lint_spec(d["spec"])
        status = "draft" if any(i["level"] == "error" for i in report) \
            else "linted"
        self.store._conn.execute(
            "UPDATE survey_definition_v1 SET status=?, lint_report_json=?,"
            " updated_at=? WHERE survey_id=? AND version=? AND"
            " status='draft'",
            (status, json.dumps(report, ensure_ascii=False), _now(),
             survey_id, d["version"]))
        self.store._conn.commit()
        return self.get_survey(survey_id)

    def lint_spec(self, spec: dict) -> list[dict]:
        issues: list[dict] = []
        qs = spec.get("questions") or []
        qids = [q.get("id") for q in qs]
        qset = set(qids)
        if len(qids) != len(qset):
            issues.append({"level": "error", "code": "dup_question_id",
                           "message": "题目 ID 重复"})
        for q in qs:
            if q.get("type") not in QUESTION_TYPES:
                issues.append({
                    "level": "error", "code": "unknown_type",
                    "message": f"题型未实现/非法: {q.get('type')}"
                               "（预留类型首阶段不得伪造）"})
            if q.get("type") in ("single_choice", "multi_choice") and \
                    not q.get("options"):
                issues.append({
                    "level": "error", "code": "no_options",
                    "message": f"{q.get('id')} 缺少选项"})
            if q.get("type") == "matrix":
                if not q.get("rows") or not q.get("options"):
                    issues.append({
                        "level": "error", "code": "matrix_incomplete",
                        "message": f"{q.get('id')} 矩阵题需要 rows 与"
                                   " options"})
            if q.get("type") == "photo":
                # UATCC T1：门头必拍不得被 min_count=0 绕过
                role = q.get("capture_role", "other")
                if role not in CAPTURE_ROLES:
                    issues.append({
                        "level": "error", "code": "capture_role",
                        "message": f"{q.get('id')} 拍摄角色非法: {role}"
                                   f"（允许 {list(CAPTURE_ROLES)}）"})
                if q.get("required") and int(q.get("min_count", 0) or 0) <= 0 \
                        and not q.get("require_storefront"):
                    issues.append({
                        "level": "error",
                        "code": "photo_required_conflict",
                        "message": f"{q.get('id')} required=true 与"
                                   " min_count=0 冲突（必填照片题必须"
                                   " 最少 1 张）"})
                if q.get("require_storefront") and role != "storefront":
                    issues.append({
                        "level": "error",
                        "code": "storefront_role_mismatch",
                        "message": f"{q.get('id')} require_storefront"
                                   "=true 时 capture_role 必须为"
                                   " storefront"})
                mx = q.get("max_count")
                if mx is not None and int(mx) < int(
                        q.get("min_count", 0) or 0):
                    issues.append({
                        "level": "error", "code": "photo_count_range",
                        "message": f"{q.get('id')} max_count 不得小于"
                                   " min_count"})
        edges = spec.get("logic_edges") or []
        adj: dict[str, list[dict]] = {}
        for e in edges:
            if e.get("from") not in qset:
                issues.append({"level": "error", "code": "edge_unknown",
                               "message": f"跳题引用未知题目: {e.get('from')}"})
                continue
            adj.setdefault(e["from"], []).append(e)
            when = e.get("when") or {}
            if not when.get("op"):
                issues.append({
                    "level": "error", "code": "edge_no_condition",
                    "message": f"{e.get('from')} 的跳题缺少条件"})
        # 冲突条件：同题同条件值多条边
        seen: dict[tuple, str] = {}
        for e in edges:
            key = (e.get("from"), json.dumps(e.get("when") or {},
                                             sort_keys=True))
            if key in seen:
                issues.append({
                    "level": "error", "code": "edge_conflict",
                    "message": f"{e.get('from')} 存在冲突跳题条件"})
            seen[key] = e.get("to") or ""
        # 可达性与循环：从首题出发 DFS（END_SKIP_* 视为终止哨兵）
        if qids:
            reachable: set[str] = set()
            stack = [qids[0]]
            guard = 0
            while stack and guard < 10000:
                guard += 1
                cur = stack.pop()
                if cur in reachable:
                    continue
                reachable.add(cur)
                real_targets = []
                for e in adj.get(cur, []):
                    to = e.get("to") or ""
                    if to and not str(to).startswith("END_") and to in qset:
                        real_targets.append(to)
                if real_targets:
                    # 有真实跳题目标：流向由边接管（不再隐式顺序）
                    stack.extend(real_targets)
                else:
                    # 无真实跳题（或仅 END_ 哨兵）：保持顺序后继
                    idx = qids.index(cur) if cur in qids else -1
                    if 0 <= idx < len(qids) - 1:
                        stack.append(qids[idx + 1])
            for qid in qids:
                if qid not in reachable:
                    issues.append({
                        "level": "error", "code": "unreachable",
                        "message": f"题目不可达: {qid}"})
            if guard >= 10000:
                issues.append({"level": "error", "code": "cycle",
                               "message": "跳题逻辑疑似循环"})
            # 显式环检测（仅跳题边）
            def has_cycle() -> bool:
                color: dict[str, int] = {}

                def dfs(n: str) -> bool:
                    color[n] = 1
                    for e in adj.get(n, []):
                        t = e.get("to") or ""
                        if not t or str(t).startswith("END_") \
                                or t not in qset:
                            continue
                        if color.get(t) == 1:
                            return True
                        if color.get(t) is None and dfs(t):
                            return True
                    color[n] = 2
                    return False
                return any(color.get(n) is None and dfs(n) for n in qset)
            if has_cycle():
                issues.append({"level": "error", "code": "cycle",
                               "message": "跳题逻辑存在循环"})
            # 缺失默认分支（warn）：有跳题边但无顺序后继说明
            for frm, es in adj.items():
                if not any(e.get("default") for e in es):
                    issues.append({
                        "level": "warn", "code": "no_default_branch",
                        "message": f"{frm} 建议显式声明默认分支"})
        if not spec.get("scoring"):
            issues.append({"level": "warn", "code": "no_scoring",
                           "message": "未配置评分规则"})
        return issues

    def publish(self, survey_id: str, *, actor: str) -> dict:
        d = self.get_survey(survey_id)
        if d["status"] not in ("linted",):
            raise SurveyError("只有 lint 通过的 draft 可发布")
        self.store._conn.execute(
            "UPDATE survey_definition_v1 SET status='published',"
            " published_at=?, updated_at=? WHERE survey_id=? AND version=?",
            (_now(), _now(), survey_id, d["version"]))
        self.store._conn.commit()
        return self.get_survey(survey_id)

    # ---------- 分配与填写 ----------

    def assign(self, *, survey_id: str, customer_id: str,
               project_id: str = "", assignee: str, actor: str) -> dict:
        # 分配始终针对该 survey 的已发布版本（不是最新草稿）
        row = self.store._conn.execute(
            "SELECT * FROM survey_definition_v1 WHERE survey_id=? AND"
            " status='published' ORDER BY version DESC LIMIT 1",
            (survey_id,)).fetchone()
        if row is None:
            raise SurveyError("只有已发布问卷可分配")
        d = dict(row)
        aid = _new_id("asg")
        now = _now()
        self.store._conn.execute(
            "INSERT INTO survey_assignment_v1 (assignment_id, survey_id,"
            " survey_version, customer_id, project_id, assignee, status,"
            " created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (aid, survey_id, d["version"], customer_id, project_id,
             assignee, "assigned", actor, now, now))
        self.store._conn.commit()
        return self.get_assignment(aid)

    def get_assignment(self, assignment_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM survey_assignment_v1 WHERE assignment_id=?",
            (assignment_id,)).fetchone()
        if row is None:
            raise SurveyError(f"assignment 不存在: {assignment_id}")
        return dict(row)

    def list_assignments(self, *, customer_id: str = "",
                         assignee: str = "") -> list[dict]:
        where, params = [], []
        if customer_id:
            where.append("customer_id=?"); params.append(customer_id)
        if assignee:
            where.append("assignee=?"); params.append(assignee)
        sql = "SELECT * FROM survey_assignment_v1"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.store._conn.execute(sql + " ORDER BY created_at",
                                        params).fetchall()
        return [dict(r) for r in rows]

    def start_response(self, *, assignment_id: str, respondent: str) -> dict:
        a = self.get_assignment(assignment_id)
        rid = _new_id("rsp")
        now = _now()
        self.store._conn.execute(
            "INSERT INTO survey_response_v1 (response_id, assignment_id,"
            " survey_id, survey_version, customer_id, respondent, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, assignment_id, a["survey_id"], a["survey_version"],
             a["customer_id"], respondent, "draft", now, now))
        self.store._conn.commit()
        return self.get_response(rid)

    def get_response(self, response_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM survey_response_v1 WHERE response_id=?",
            (response_id,)).fetchone()
        if row is None:
            raise SurveyError(f"response 不存在: {response_id}")
        d = dict(row)
        d["answers"] = json.loads(d["answers_json"] or "{}")
        d["scores"] = json.loads(d["scores_json"] or "{}")
        return d

    def list_responses(self, *, survey_id: str = "",
                       customer_id: str = "") -> list[dict]:
        where, params = [], []
        if survey_id:
            where.append("survey_id=?"); params.append(survey_id)
        if customer_id:
            where.append("customer_id=?"); params.append(customer_id)
        sql = "SELECT * FROM survey_response_v1"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self.store._conn.execute(sql + " ORDER BY created_at",
                                        params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["answers"] = json.loads(d["answers_json"] or "{}")
            d["scores"] = json.loads(d["scores_json"] or "{}")
            out.append(d)
        return out

    def save_answers(self, response_id: str,
                     answers: dict[str, Any]) -> dict:
        r = self.get_response(response_id)
        if r["status"] != "draft":
            raise SurveyError("已提交响应不得直接改答案；请走 correction")
        merged = {**r["answers"], **answers}
        self.store._conn.execute(
            "UPDATE survey_response_v1 SET answers_json=?, updated_at=?"
            " WHERE response_id=?",
            (json.dumps(merged, ensure_ascii=False), _now(), response_id))
        self.store._conn.commit()
        return self.get_response(response_id)

    # ---------- 跳题可见性 + 提交 + 评分 ----------

    def visible_questions(self, spec: dict,
                          answers: dict[str, Any]) -> list[str]:
        """按答案求值跳题边，返回实际可见题目（被跳过的题目不作答）。"""
        qs = spec.get("questions") or []
        qids = [q["id"] for q in qs]
        skipped: set[str] = set()
        for e in spec.get("logic_edges") or []:
            when = e.get("when") or {}
            ans = (answers.get(e.get("from")) or {}).get("value")
            hit = False
            if when.get("op") == "eq":
                hit = ans == when.get("value")
            elif when.get("op") == "ne":
                hit = ans != when.get("value")
            if hit:
                to = e.get("to") or ""
                if str(to).startswith("END_"):
                    # 跳到终止哨兵：其后属于被跳 section 的题目省略处理
                    frm_idx = qids.index(e["from"]) \
                        if e.get("from") in qids else -1
                    skipped.update(qids[frm_idx + 1:])
                elif to in qids:
                    # 直接跳题：中间题目被跳过
                    frm_idx = qids.index(e["from"]) \
                        if e.get("from") in qids else -1
                    to_idx = qids.index(to)
                    if to_idx > frm_idx:
                        skipped.update(qids[frm_idx + 1:to_idx])
        return [q for q in qids if q not in skipped]

    def submit(self, response_id: str, *, actor: str) -> dict:
        r = self.get_response(response_id)
        if r["status"] != "draft":
            raise SurveyError("响应已提交")
        spec = self.get_survey(r["survey_id"], r["survey_version"])["spec"]
        visible = self.visible_questions(spec, r["answers"])
        qmap = {q["id"]: q for q in spec.get("questions") or []}
        missing = []
        for qid in visible:
            q = qmap[qid]
            if q["type"] == "description":
                continue  # 说明题不作答
            if q["type"] == "photo":
                # UATCC T1：照片契约（门头必拍不得绕过；只计当前
                # response/question 下状态有效的 media）
                medias = [m for m in self.list_media(
                    response_id, question_id=qid)
                    if m.get("status", "active") == "active"]
                need_any = bool(q.get("required")
                                or q.get("require_storefront")
                                or int(q.get("min_count", 0) or 0) > 0)
                if q.get("require_storefront"):
                    sf = [m for m in medias
                          if m.get("capture_role") == "storefront"]
                    if not sf:
                        missing.append(
                            f"{qid}(缺门头照 storefront：必须至少 1 张"
                            " capture_role=storefront 的照片)")
                mn = int(q.get("min_count", 0) or 0)
                if need_any and not medias and mn <= 0:
                    missing.append(f"{qid}(照片缺失：必拍题不得无照片)")
                elif mn > 0 and len(medias) < mn:
                    missing.append(
                        f"{qid}(照片不足：需至少 {mn} 张，当前"
                        f" {len(medias)} 张)")
                mx = q.get("max_count")
                if mx is not None and len(medias) > int(mx):
                    missing.append(
                        f"{qid}(照片超出上限：最多 {int(mx)} 张，当前"
                        f" {len(medias)} 张)")
                continue
            if q.get("required") and qid not in r["answers"]:
                missing.append(qid)
            if q["type"] == "matrix" and q.get("required"):
                ans = (r["answers"].get(qid) or {}).get("value") or {}
                unanswered = [row["id"] for row in q.get("rows", [])
                              if row["id"] not in ans]
                if unanswered:
                    missing.append(f"{qid}(矩阵未填全)")
        if missing:
            raise SurveyError(f"必填未完成: {', '.join(missing)}")
        scores = self._score(spec, r["answers"])
        self.store._conn.execute(
            "UPDATE survey_response_v1 SET status='submitted',"
            " scores_json=?, score_version=1, submitted_at=?, updated_at=?"
            " WHERE response_id=?",
            (json.dumps(scores, ensure_ascii=False), _now(), _now(),
             response_id))
        self.store._conn.execute(
            "UPDATE survey_assignment_v1 SET status='completed',"
            " updated_at=? WHERE assignment_id=?",
            (_now(), r["assignment_id"]))
        self.store._conn.commit()
        return self.get_response(response_id)

    def _score(self, spec: dict, answers: dict[str, Any]) -> dict:
        scoring = spec.get("scoring") or {}
        total = 0.0
        detail: dict[str, float] = {}
        for rule in scoring.get("rules") or []:
            qid = rule.get("question")
            ans = answers.get(qid)
            if ans is None:
                continue
            weight = float(rule.get("weight") or 1)
            if "map" in rule:
                val = ans.get("value")
                if isinstance(val, dict):
                    # 矩阵题：逐行按 map 计分
                    pts = sum(float(rule["map"].get(v, 0))
                              for v in val.values())
                else:
                    pts = float(rule["map"].get(val, 0))
            else:
                try:
                    pts = float(ans.get("value") or 0)
                except (TypeError, ValueError):
                    pts = 0.0
            contribution = pts * weight
            detail[qid] = contribution
            total += contribution
        return {"total": total,
                "formula": scoring.get("formula", "sum"),
                "scoring_version": scoring.get("version", 1),
                # SI2-010：兼容非 dict 包裹的答案（不得 500）
                "inputs": {k: (v.get("value") if isinstance(v, dict)
                               else v)
                           for k, v in answers.items()},
                "detail": detail}

    # ---------- 拍照题：证据 + 识别 suggestion + 人工终审 ----------

    def attach_media(self, *, response_id: str, question_id: str,
                     location: dict | None = None, taken_at: str = "",
                     device: str = "", quality: dict | None = None,
                     image_b64: str = "", actor: str,
                     capture_role: str | None = None) -> dict:
        r = self.get_response(response_id)
        if r["status"] != "draft":
            raise SurveyError("已提交响应不得追加媒体")
        spec = self.get_survey(r["survey_id"], r["survey_version"])["spec"]
        q = next((q for q in spec.get("questions") or []
                  if q["id"] == question_id), None)
        if q is None or q["type"] != "photo":
            raise SurveyError(f"题目不是拍照题: {question_id}")
        # UATCC T1：拍摄角色必须显式合法；未传时默认取题目配置；
        # require_storefront 题不得以非门头角色冒充。
        role = capture_role or q.get("capture_role") or "other"
        if role not in CAPTURE_ROLES:
            raise SurveyError(
                f"capture_role 非法: {role}（允许 {list(CAPTURE_ROLES)}）")
        if q.get("require_storefront") and q.get("capture_role") \
                == "storefront" and role != "storefront":
            raise SurveyError(
                "门头必拍题：上传照片必须 capture_role=storefront，"
                f"当前为 {role}")
        mid = _new_id("med")
        evidence_ref = ""
        run_id = ""
        suggestion: dict = {}
        suggestion_status = "none"
        if image_b64 and self.gateway is not None and q.get("recognition"):
            # 识别只是 suggestion：进统一 gateway 链（事件/证据/用量）；
            # profile 取题目配置（UATCC T1），缺省 standard 生产链。
            out = self.gateway.submit(
                command_kind="vision.recognition.create",
                params={"images": [[f"{mid}.jpg", image_b64]],
                        "recognition_profile_id": q.get(
                            "recognition_profile_id")
                            or "production_legacy",
                        "service_tier": "standard"},
                actor=actor, source="internal",
                customer_id=r["customer_id"])
            run_id = out.get("run_id", "")
            result = (out.get("result") or {})
            suggestion = {"status": out.get("status"),
                          "task_id": result.get("task_id"),
                          "trace_id": result.get("trace_id"),
                          "evidence_bundle_id":
                              result.get("evidence_bundle_id")}
            evidence_ref = f"evidence_bundle:{result.get('evidence_bundle_id')}"
            suggestion_status = "pending" if out.get("status") \
                == "succeeded" else "failed"
        self.store._conn.execute(
            "INSERT INTO survey_media_v1 (media_id, response_id,"
            " question_id, evidence_ref, location_json, taken_at, device,"
            " quality_json, recognition_run_id, suggestion_json,"
            " suggestion_status, capture_role, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, response_id, question_id, evidence_ref,
             json.dumps(location or {}, ensure_ascii=False), taken_at,
             device, json.dumps(quality or {}, ensure_ascii=False),
             run_id, json.dumps(suggestion, ensure_ascii=False),
             suggestion_status, role, "active", _now()))
        self.store._conn.commit()
        return self.get_media(mid)

    def delete_media(self, media_id: str, *, actor: str) -> dict:
        """软删除：追加式标记 deleted（不物理删除，提交时不计数）。"""
        m = self.get_media(media_id)
        self.store._conn.execute(
            "UPDATE survey_media_v1 SET status='deleted'"
            " WHERE media_id=?", (media_id,))
        self.store._conn.commit()
        return self.get_media(media_id)

    def get_media(self, media_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM survey_media_v1 WHERE media_id=?",
            (media_id,)).fetchone()
        if row is None:
            raise SurveyError(f"media 不存在: {media_id}")
        d = dict(row)
        d["location"] = json.loads(d["location_json"] or "{}")
        d["quality"] = json.loads(d["quality_json"] or "{}")
        d["suggestion"] = json.loads(d["suggestion_json"] or "{}")
        return d

    def list_media(self, response_id: str,
                   question_id: str = "") -> list[dict]:
        if question_id:
            rows = self.store._conn.execute(
                "SELECT media_id FROM survey_media_v1 WHERE response_id=?"
                " AND question_id=? ORDER BY created_at",
                (response_id, question_id)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT media_id FROM survey_media_v1 WHERE response_id=?"
                " ORDER BY created_at", (response_id,)).fetchall()
        return [self.get_media(r["media_id"]) for r in rows]

    def review_suggestion(self, media_id: str, *, decision: str,
                          final_value: Any = None, actor: str) -> dict:
        """模型输出只是 suggestion；accept/reject/modify 后才成 final。

        拒绝/修改会写入评估反馈事件（training_truth=false）：进入
        问卷报表与模型评估链，但绝不自动成为训练真值。
        """
        if decision not in ("accepted", "rejected", "modified"):
            raise SurveyError("decision 只支持 accepted/rejected/modified")
        m = self.get_media(media_id)
        final = final_value if final_value is not None else (
            m["suggestion"] if decision == "accepted" else None)
        self.store._conn.execute(
            "UPDATE survey_media_v1 SET suggestion_status=?,"
            " final_value_json=?, decided_by=? WHERE media_id=?",
            (decision, json.dumps(final, ensure_ascii=False), actor,
             media_id))
        self.store._conn.commit()
        # 评估反馈链：append-only 事件；training_truth 恒为 False
        try:
            self.store.emit_event(
                event_id=_new_id("evt"),
                event_type="survey.suggestion.reviewed",
                run_id=m["recognition_run_id"],
                actor_type="human", actor_id=actor,
                subject_type="survey_media", subject_id=media_id,
                payload={"decision": decision, "training_truth": False,
                         "note": "人工终审反馈；不得自动成为训练真值"})
        except Exception:
            pass
        # final answer 写回响应答案（photo 题）
        r = self.get_response(m["response_id"])
        if r["status"] == "draft" and decision in ("accepted", "modified"):
            answers = {**r["answers"], m["question_id"]: {
                "value": final, "final": True, "media_id": media_id,
                "decided_by": actor}}
            self.save_answers(m["response_id"], answers)
        return self.get_media(media_id)

    # ---------- 后台修正 ----------

    def correct_answer(self, *, response_id: str, question_id: str,
                       new_value: Any, reason: str, actor: str,
                       approver: str = "") -> dict:
        """后台改答案：只走 correction event + 评分重算版本。"""
        if not reason:
            raise SurveyError("修正必须填写原因")
        r = self.get_response(response_id)
        old = r["answers"].get(question_id)
        self.store._conn.execute(
            "INSERT INTO survey_answer_correction_v1 (response_id,"
            " question_id, old_value_json, new_value_json, reason, actor,"
            " approver, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (response_id, question_id,
             json.dumps(old, ensure_ascii=False),
             json.dumps(new_value, ensure_ascii=False), reason, actor,
             approver, _now()))
        answers = {**r["answers"], question_id: {
            **(new_value if isinstance(new_value, dict)
               else {"value": new_value}),
            "corrected": True, "correction_reason": reason}}
        spec = self.get_survey(r["survey_id"], r["survey_version"])["spec"]
        scores = self._score(spec, answers)
        self.store._conn.execute(
            "UPDATE survey_response_v1 SET answers_json=?, scores_json=?,"
            " score_version=score_version+1, updated_at=?"
            " WHERE response_id=?",
            (json.dumps(answers, ensure_ascii=False),
             json.dumps(scores, ensure_ascii=False), _now(), response_id))
        self.store._conn.commit()
        return self.get_response(response_id)

    def list_corrections(self, response_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM survey_answer_correction_v1 WHERE response_id=?"
            " ORDER BY correction_id", (response_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 报表输入 ----------

    def report(self, *, survey_id: str, customer_id: str = "") -> dict:
        """报表输入：final 答案 + 评分（BI 只读消费本端点）。"""
        responses = self.list_responses(survey_id=survey_id,
                                        customer_id=customer_id)
        submitted = [r for r in responses if r["status"] == "submitted"]
        total_score = sum(r["scores"].get("total", 0) for r in submitted)
        return {"survey_id": survey_id, "customer_id": customer_id,
                "responses": len(responses),
                "submitted": len(submitted),
                "total_score": total_score,
                "avg_score": (total_score / len(submitted))
                if submitted else None,
                "score_version_max": max(
                    (r["score_version"] for r in submitted), default=0),
                "items": [{"response_id": r["response_id"],
                           "respondent": r["respondent"],
                           "status": r["status"],
                           "scores": r["scores"],
                           "answers": r["answers"]}
                          for r in responses]}
