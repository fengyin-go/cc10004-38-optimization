"""推导服务门面：把解析器、求值器、证据仓和既有业务表串成可调用的业务能力。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.derive.engine import evaluate
from app.services.derive.fields import (
    FIELD_BY_KEY,
    FieldAmbiguous,
    catalog_payload,
    resolve_field,
)
from app.services.derive.parser import ExpressionError, parse_expression
from app.services.derive.store import (
    FILTER_MODULE,
    SAMPLE_MODULE,
    TAG_MODULE,
    EvidenceStore,
    evidence,
    now_text,
)
from app.store import store


class AmbiguityRequired(Exception):
    """HTTP 409：表达式含同名字段冲突，需要业务人员先确认身份。"""

    def __init__(self, ambiguities: list[dict[str, Any]]) -> None:
        self.ambiguities = ambiguities
        super().__init__("存在同名字段冲突，等待身份确认")


def _direct_field_labels(node: dict[str, Any], acc: set[str] | None = None) -> set[str]:
    """收集表达式里直接引用的字段名（规则内部的字段由规则自己的身份映射负责）。"""
    if acc is None:
        acc = set()
    if node.get("type") == "compare":
        acc.add(str(node["field"]))
    elif node.get("type") == "logic":
        for child in node.get("children", []):
            _direct_field_labels(child, acc)
    return acc


def check_ambiguity(ast: dict[str, Any], identity_map: dict[str, str]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for label in sorted(_direct_field_labels(ast)):
        try:
            resolve_field(label, identity_map)
        except FieldAmbiguous as exc:
            pending.append({
                "field": label,
                "candidates": [
                    {"key": item.key, "label": item.label, "source": item.source, "kind": item.kind}
                    for item in exc.candidates
                ],
            })
        except KeyError:
            raise ExpressionError(f"字段「{label}」不在字段目录中，请改用已登记字段")
    return pending


def require_resolved(ast: dict[str, Any], identity_map: dict[str, str]) -> None:
    pending = check_ambiguity(ast, identity_map)
    if pending:
        raise AmbiguityRequired(pending)


# ---------------- 演示样本 ----------------
class SampleService:
    def list_objects(self) -> list[dict[str, Any]]:
        return store.rows(SAMPLE_MODULE)

    def get_object(self, object_id: str) -> dict[str, Any] | None:
        for row in store.rows(SAMPLE_MODULE):
            if row["客户编号"] == object_id:
                return row
        return None

    def update_object(self, object_id: str, values: dict[str, Any]) -> dict[str, Any]:
        row = self.get_object(object_id)
        if row is None:
            raise KeyError(f"样本对象 {object_id} 不存在")
        for key in FIELD_BY_KEY:
            if key in values:
                row[key] = values[key]
        return row

    def reset_objects(self, seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = store.rows(SAMPLE_MODULE)
        rows.clear()
        rows.extend(deepcopy(seed_rows))
        return rows

    def catalog(self) -> list[dict[str, str]]:
        return catalog_payload()


# ---------------- 数据筛选：试算与条件版本 ----------------
class FilterDeriveService:
    def __init__(self, backend: EvidenceStore) -> None:
        self.evidence = backend

    def prepare_condition(self, rule_id: int, condition_text: str,
                          identity_map: dict[str, str] | None, *, note: str) -> dict[str, Any]:
        """登记/修订规则条件：解析、冲突检查、升版本。"""
        ast = parse_expression(condition_text)
        merged = {**(self.evidence.filter_meta.get(rule_id, {}).get("identityMap", {})), **(identity_map or {})}
        require_resolved(ast, merged)
        meta = self.evidence.register_filter(rule_id, condition_text, ast, merged, note=note)
        return meta

    def trial(self, rule_id: int, object_id: str | None = None) -> dict[str, Any]:
        """规则试算：对全部（或指定）样本对象执行条件并保留分步 trace。"""
        row = store.find(FILTER_MODULE, rule_id)
        if row is None:
            raise KeyError(f"筛选规则 {rule_id} 不存在")
        meta = self.evidence.filter_meta_by_id(rule_id)
        if meta is None:
            raise ExpressionError("该规则还没有可执行条件，请先保存条件表达式")
        version = meta["version"]
        version_data = meta["history"][version]
        targets = [self._require_object(object_id)] if object_id else store.rows(SAMPLE_MODULE)
        run = self.evidence.add_run({
            "scope": FILTER_MODULE,
            "ownerId": rule_id,
            "version": version,
            "expression": version_data["conditionText"],
            "results": [],
        })
        results = run["results"]
        for obj in targets:
            hit, trace = evaluate(
                version_data["ast"], obj,
                identity_map=version_data["identityMap"],
                rule_resolver=self.evidence.rule_resolver,
            )
            results.append({
                "objectId": obj["客户编号"],
                "objectLabel": obj["客户名称"],
                "hit": hit,
                "trace": trace,
            })
        # 试算只产生运行记录，不自动确认；业务人员检查无误后再手动确认，才生成有效解释
        return {
            "runId": run["runId"],
            "ranAt": run["ranAt"],
            "ruleId": rule_id,
            "ruleCode": row.get("规则编号"),
            "version": version,
            "status": row.get("status"),
            "conditionText": version_data["conditionText"],
            "identityMap": version_data["identityMap"],
            "results": results,
            "coverageCount": sum(1 for item in results if item["hit"]),
            "totalCount": len(results),
            "stale": [],
        }

    def confirm_trial(self, rule_id: int, run_id: str, object_id: str, confirmed_by: str) -> tuple[dict[str, Any], bool]:
        run = self._get_run(FILTER_MODULE, rule_id, run_id)
        result = self._find_result(run, object_id)
        return self.evidence.confirm_explanation(
            {
                "scope": FILTER_MODULE, "ownerId": rule_id, "version": run["version"],
                "objectId": object_id, "objectLabel": result["objectLabel"],
                "hit": result["hit"], "trace": result["trace"],
                "expression": run.get("expression"), "runId": run_id,
            },
            confirmed_by=confirmed_by,
        )

    def confirm_all(self, rule_id: int, run_id: str, confirmed_by: str) -> dict[str, Any]:
        run = self._get_run(FILTER_MODULE, rule_id, run_id)
        created, deduped = 0, 0
        for result in run["results"]:
            _, was_dup = self.evidence.confirm_explanation(
                {
                    "scope": FILTER_MODULE, "ownerId": rule_id, "version": run["version"],
                    "objectId": result["objectId"], "objectLabel": result["objectLabel"],
                    "hit": result["hit"], "trace": result["trace"],
                    "expression": run.get("expression"), "runId": run_id,
                },
                confirmed_by=confirmed_by,
            )
            if was_dup:
                deduped += 1
            else:
                created += 1
        return {"created": created, "deduped": deduped, "total": created + deduped}

    def explanations(self, rule_id: int, version: int | None = None) -> list[dict[str, Any]]:
        items = self.evidence.list_explanations(scope=FILTER_MODULE, owner_id=rule_id, version=version)
        return [self._decorate(item) for item in items]

    def _decorate(self, item: dict[str, Any]) -> dict[str, Any]:
        item = dict(item)
        item["staleNotes"] = self.evidence.staleness(item.get("snapshots", []))
        item["evidenceState"] = "本次未命中" if not item["hit"] else "命中"
        return item

    def _require_object(self, object_id: str) -> dict[str, Any]:
        obj = SampleService().get_object(object_id)
        if obj is None:
            raise KeyError(f"样本对象 {object_id} 不存在")
        return obj

    def _get_run(self, scope: str, owner_id: int, run_id: str) -> dict[str, Any]:
        for run in self.evidence.runs:
            if run["runId"] == run_id and run["scope"] == scope and run["ownerId"] == owner_id:
                return run
        raise KeyError(f"运行记录 {run_id} 不存在或不属于当前归属")

    @staticmethod
    def _find_result(run: dict[str, Any], object_id: str) -> dict[str, Any]:
        for result in run["results"]:
            if result["objectId"] == object_id:
                return result
        raise KeyError(f"运行 {run['runId']} 中没有对象 {object_id} 的结果")


# ---------------- 数据标签：重算与解释确认 ----------------
class TagDeriveService:
    def __init__(self, backend: EvidenceStore) -> None:
        self.evidence = backend

    def prepare_expression(self, tag_id: int, expression: str,
                           identity_map: dict[str, str] | None, *, note: str,
                           new_version: bool = True) -> dict[str, Any]:
        ast = parse_expression(expression)
        current = self.evidence.get_tag_version(tag_id)
        base_map = current["identityMap"] if current else {}
        merged = {**base_map, **(identity_map or {})}
        require_resolved(ast, merged)
        if not new_version and current is not None:
            current.update({
                "expression": expression, "ast": ast, "identityMap": merged,
                "createdAt": now_text(), "note": note,
            })
            version_item = current
        else:
            version_item = self.evidence.add_tag_version(tag_id, expression, ast, merged, note=note)
        # 同步标签表上的计算表达式，保持列表页可读
        row = store.find(TAG_MODULE, tag_id)
        if row is not None:
            row["计算表达式"] = expression
        return version_item

    def recompute(self, tag_id: int, *, version: int | None = None,
                  object_id: str | None = None, identity_map: dict[str, str] | None = None) -> dict[str, Any]:
        row = store.find(TAG_MODULE, tag_id)
        if row is None:
            raise KeyError(f"标签定义 {tag_id} 不存在或已归档")
        version_item = self.evidence.get_tag_version(tag_id, version)
        if version_item is None:
            raise ExpressionError("该标签没有计算证据：历史标签请先登记表达式并完成首次重算")
        merged_map = {**version_item["identityMap"], **(identity_map or {})}
        # 同名字段冲突：已确认身份为准，仍未确认的返回 409 让前端弹窗
        pending = check_ambiguity(version_item["ast"], merged_map)
        if pending:
            raise AmbiguityRequired(pending)
        if identity_map:
            # 本次确认的身份回写到版本，后续重算直接沿用
            version_item["identityMap"] = merged_map

        targets = [self._require_object(object_id)] if object_id else store.rows(SAMPLE_MODULE)
        run = self.evidence.add_run({
            "scope": TAG_MODULE,
            "ownerId": tag_id,
            "version": version_item["version"],
            "expression": version_item["expression"],
            "results": [],
        })
        for obj in targets:
            hit, trace = evaluate(
                version_item["ast"], obj,
                identity_map=merged_map,
                rule_resolver=self.evidence.rule_resolver,
            )
            run["results"].append({
                "objectId": obj["客户编号"],
                "objectLabel": obj["客户名称"],
                "hit": hit,
                "trace": trace,
            })
        return self.run_payload(tag_id, run, row)

    def run_payload(self, tag_id: int, run: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        return {
            "runId": run["runId"],
            "ranAt": run["ranAt"],
            "tagId": tag_id,
            "tagCode": row.get("标签编号"),
            "tagName": row.get("标签名称"),
            "version": run["version"],
            "expression": run["expression"],
            "coverageCount": sum(1 for item in run["results"] if item["hit"]),
            "totalCount": len(run["results"]),
            "results": run["results"],
        }

    def runs(self, tag_id: int) -> list[dict[str, Any]]:
        row = store.find(TAG_MODULE, tag_id)
        return [
            {
                "runId": item["runId"], "ranAt": item["ranAt"],
                "version": item["version"], "expression": item.get("expression"),
                "coverageCount": sum(1 for r in item["results"] if r["hit"]),
                "totalCount": len(item["results"]),
            }
            for item in self.evidence.list_runs(scope=TAG_MODULE, owner_id=tag_id)
        ]

    def run_detail(self, tag_id: int, run_id: str) -> dict[str, Any]:
        row = store.find(TAG_MODULE, tag_id)
        if row is None:
            raise KeyError(f"标签定义 {tag_id} 不存在")
        for run in self.evidence.runs:
            if run["runId"] == run_id and run["scope"] == TAG_MODULE and run["ownerId"] == tag_id:
                return self.run_payload(tag_id, run, row)
        raise KeyError(f"运行记录 {run_id} 不存在")

    def confirm(self, tag_id: int, run_id: str, object_id: str, confirmed_by: str) -> tuple[dict[str, Any], bool]:
        run = self._get_run(tag_id, run_id)
        result = FilterDeriveService._find_result(run, object_id)
        return self.evidence.confirm_explanation(
            {
                "scope": TAG_MODULE, "ownerId": tag_id, "version": run["version"],
                "objectId": object_id, "objectLabel": result["objectLabel"],
                "hit": result["hit"], "trace": result["trace"],
                "expression": run.get("expression"), "runId": run_id,
            },
            confirmed_by=confirmed_by,
        )

    def confirm_all(self, tag_id: int, run_id: str, confirmed_by: str) -> dict[str, Any]:
        run = self._get_run(tag_id, run_id)
        created, deduped = 0, 0
        for result in run["results"]:
            _, was_dup = self.evidence.confirm_explanation(
                {
                    "scope": TAG_MODULE, "ownerId": tag_id, "version": run["version"],
                    "objectId": result["objectId"], "objectLabel": result["objectLabel"],
                    "hit": result["hit"], "trace": result["trace"],
                    "expression": run.get("expression"), "runId": run_id,
                },
                confirmed_by=confirmed_by,
            )
            if was_dup:
                deduped += 1
            else:
                created += 1
        return {"created": created, "deduped": deduped, "total": created + deduped}

    def explanation_board(self, tag_id: int, version: int | None = None) -> dict[str, Any]:
        """解释卡数据：严格区分「旧证据缺失」和「本次未命中」。"""
        row = store.find(TAG_MODULE, tag_id)
        if row is None:
            raise KeyError(f"标签定义 {tag_id} 不存在")
        if self.evidence.is_legacy_tag(tag_id):
            return {
                "tagId": tag_id,
                "tagCode": row.get("标签编号"),
                "legacy": True,
                "message": "旧证据缺失：该标签在证据能力上线前已存在，没有保存计算过程，登记表达式并重算后才能生成分步解释",
                "versions": [],
                "explanations": [],
            }
        versions = [
            {"version": item["version"], "expression": item["expression"],
             "createdAt": item["createdAt"], "note": item["note"],
             "identityMap": item["identityMap"]}
            for item in self.evidence.ensure_tag_versions(tag_id)
        ]
        items = self.evidence.list_explanations(scope=TAG_MODULE, owner_id=tag_id, version=version)
        decorated = []
        for item in items:
            decorated.append({
                **dict(item),
                "staleNotes": self.evidence.staleness(item.get("snapshots", [])),
                "evidenceState": "本次未命中" if not item["hit"] else "命中",
            })
        return {
            "tagId": tag_id,
            "tagCode": row.get("标签编号"),
            "legacy": False,
            "message": "",
            "currentVersion": self.evidence.get_tag_version(tag_id)["version"],
            "versions": versions,
            "explanations": decorated,
        }

    def _require_object(self, object_id: str) -> dict[str, Any]:
        obj = SampleService().get_object(object_id)
        if obj is None:
            raise KeyError(f"样本对象 {object_id} 不存在")
        return obj

    def _get_run(self, tag_id: int, run_id: str) -> dict[str, Any]:
        for run in self.evidence.runs:
            if run["runId"] == run_id and run["scope"] == TAG_MODULE and run["ownerId"] == tag_id:
                return run
        raise KeyError(f"运行记录 {run_id} 不存在或不属于标签 {tag_id}")


sample_service = SampleService()
filter_derive_service = FilterDeriveService(evidence)
tag_derive_service = TagDeriveService(evidence)
