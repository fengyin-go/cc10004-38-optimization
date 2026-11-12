"""推导证据仓（内存实现）。

收四类数据，全部挂在单例 evidence 上：
1. filter_meta：筛选规则的条件 AST、版本与修订历史。规则状态仍以通用 store 的行为准，
   证据里只额外保存条件文本/AST/身份映射，避免和既有状态流转打架。
2. tag_versions：标签每个版本的表达式、AST 与已确认的同名字段身份。
3. runs：每一次重算/试算的原始运行记录。两个版本同时重算各自一条，互不覆盖。
4. explanations：业务人员确认过的有效解释，按 (作用域, 归属ID, 版本, 对象ID) 去重，
   重复确认只保留一份；证据内嵌规则快照，规则之后停用/修订不改动历史解释。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

FILTER_MODULE = "filter"
TAG_MODULE = "tag"
SAMPLE_MODULE = "sample_object"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _walk_trace(trace: dict[str, Any]):
    yield trace
    for step in trace.get("steps", []) or []:
        yield from _walk_trace(step)


def extract_snapshots(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """从解释树里抽出全部规则引用快照，用于过期比对与跨模块跳转。"""
    snapshots: list[dict[str, Any]] = []
    for node in _walk_trace(trace):
        if node.get("kind") == "rule" and node.get("snapshot"):
            snapshots.append(dict(node["snapshot"]))
    return snapshots


class EvidenceStore:
    def __init__(self) -> None:
        self.filter_meta: dict[int, dict[str, Any]] = {}
        self.tag_versions: dict[int, list[dict[str, Any]]] = {}
        self.runs: list[dict[str, Any]] = []
        self.explanations: list[dict[str, Any]] = []
        self._run_seq = 0
        self._expl_seq = 0

    # ---------- 筛选规则 ----------
    def register_filter(self, rule_id: int, condition_text: str, ast: dict[str, Any],
                        identity_map: dict[str, str], *, note: str = "初始条件") -> dict[str, Any]:
        existing = self.filter_meta.get(rule_id)
        version = 1
        if existing is None:
            meta = {
                "id": rule_id,
                "version": version,
                "identityMap": dict(identity_map),
                "revisions": [{
                    "version": version, "conditionText": condition_text,
                    "changedAt": now_text(), "note": note,
                }],
                "history": {version: {
                    "conditionText": condition_text, "ast": ast,
                    "identityMap": dict(identity_map),
                }},
            }
            self.filter_meta[rule_id] = meta
        else:
            version = existing["version"] + 1
            existing["version"] = version
            existing["identityMap"] = dict(identity_map)
            existing["history"][version] = {
                "conditionText": condition_text, "ast": ast,
                "identityMap": dict(identity_map),
            }
            existing["revisions"].append({
                "version": version, "conditionText": condition_text,
                "changedAt": now_text(), "note": note,
            })
        return self.filter_meta[rule_id]

    def filter_meta_by_id(self, rule_id: int) -> dict[str, Any] | None:
        return self.filter_meta.get(rule_id)

    def find_filter_row_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(FILTER_MODULE):
            if str(row.get("规则编号")) == code:
                return row
        return None

    def rule_resolver(self, code: str) -> dict[str, Any] | None:
        """求值器回调：按编号取规则的当前条件 + 当前状态 + 历史版本信息。"""
        row = self.find_filter_row_by_code(code)
        if row is None:
            return None
        meta = self.filter_meta.get(int(row["id"]))
        if meta is None:
            return None
        version = meta["version"]
        snapshot_version = meta["history"][version]
        return {
            "id": row["id"],
            "code": code,
            "version": version,
            "status": row.get("status", "草稿"),
            "conditionText": snapshot_version["conditionText"],
            "ast": snapshot_version["ast"],
            "identityMap": snapshot_version["identityMap"],
            "revisions": list(meta["revisions"]),
        }

    def filter_payload(self, rule_id: int) -> dict[str, Any] | None:
        meta = self.filter_meta.get(rule_id)
        if meta is None:
            return None
        row = store.find(FILTER_MODULE, rule_id)
        return {
            "ruleId": rule_id,
            "ruleCode": row.get("规则编号") if row else None,
            "version": meta["version"],
            "status": row.get("status") if row else None,
            "identityMap": dict(meta["identityMap"]),
            "revisions": list(meta["revisions"]),
            "conditionText": meta["history"][meta["version"]]["conditionText"],
        }

    # ---------- 标签版本 ----------
    def ensure_tag_versions(self, tag_id: int) -> list[dict[str, Any]]:
        return self.tag_versions.setdefault(tag_id, [])

    def add_tag_version(self, tag_id: int, expression: str, ast: dict[str, Any],
                        identity_map: dict[str, str], *, note: str) -> dict[str, Any]:
        versions = self.ensure_tag_versions(tag_id)
        version = len(versions) + 1
        item = {
            "version": version,
            "expression": expression,
            "ast": ast,
            "identityMap": dict(identity_map),
            "createdAt": now_text(),
            "note": note,
        }
        versions.append(item)
        return item

    def get_tag_version(self, tag_id: int, version: int | None = None) -> dict[str, Any] | None:
        versions = self.tag_versions.get(tag_id)
        if not versions:
            return None
        if version is None:
            return versions[-1]
        for item in versions:
            if item["version"] == version:
                return item
        return None

    def is_legacy_tag(self, tag_id: int) -> bool:
        """没有任何计算证据（无版本）的历史标签。"""
        return not self.tag_versions.get(tag_id)

    # ---------- 运行记录 ----------
    def add_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._run_seq += 1
        run = {"runId": f"RUN-{self._run_seq:04d}", "ranAt": now_text(), **payload}
        self.runs.append(run)
        return run

    def list_runs(self, *, scope: str | None = None, owner_id: int | None = None) -> list[dict[str, Any]]:
        result = self.runs
        if scope:
            result = [item for item in result if item["scope"] == scope]
        if owner_id is not None:
            result = [item for item in result if item.get("ownerId") == owner_id]
        return list(reversed(result))

    # ---------- 确认解释 ----------
    def _find_explanation(self, scope: str, owner_id: int, version: int, object_id: str) -> dict[str, Any] | None:
        for item in self.explanations:
            if (item["scope"] == scope and item["ownerId"] == owner_id
                    and item["version"] == version and item["objectId"] == object_id):
                return item
        return None

    def confirm_explanation(self, run: dict[str, Any], *, confirmed_by: str) -> tuple[dict[str, Any], bool]:
        """确认一条解释；同一 (作用域, 归属, 版本, 对象) 重复确认只保留一份。

        返回 (解释, 是否命中过去重)。新版本是新的唯一键，不会覆盖旧版本的解释。
        """
        existing = self._find_explanation(run["scope"], run["ownerId"], run["version"], run["objectId"])
        snapshots = extract_snapshots(run["trace"])
        if existing is not None:
            existing.update({
                "hit": run["hit"],
                "trace": run["trace"],
                "expression": run.get("expression"),
                "runId": run["runId"],
                "confirmedAt": now_text(),
                "confirmedBy": confirmed_by,
                "snapshots": snapshots,
            })
            existing["deduped"] = True
            return existing, True

        self._expl_seq += 1
        expl = {
            "explId": f"EXPL-{self._expl_seq:04d}",
            "scope": run["scope"],
            "ownerId": run["ownerId"],
            "version": run["version"],
            "objectId": run["objectId"],
            "objectLabel": run.get("objectLabel", run["objectId"]),
            "hit": run["hit"],
            "trace": run["trace"],
            "expression": run.get("expression"),
            "runId": run["runId"],
            "confirmedAt": now_text(),
            "confirmedBy": confirmed_by,
            "snapshots": snapshots,
            "deduped": False,
        }
        self.explanations.append(expl)
        return expl, False

    def list_explanations(self, *, scope: str | None = None, owner_id: int | None = None,
                          version: int | None = None) -> list[dict[str, Any]]:
        result = self.explanations
        if scope:
            result = [item for item in result if item["scope"] == scope]
        if owner_id is not None:
            result = [item for item in result if item["ownerId"] == owner_id]
        if version is not None:
            result = [item for item in result if item["version"] == version]
        return list(reversed(result))

    def staleness(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把解释里的规则快照和筛选模块当前条件逐条比对，给出过期原因。

        停用与修订可能同时发生，原因全部累积返回，业务人员能一次看清。
        """
        notes: list[dict[str, Any]] = []
        for snap in snapshots:
            row = store.find(FILTER_MODULE, int(snap["ruleId"]))
            meta = self.filter_meta.get(int(snap["ruleId"]))
            reasons: list[str] = []
            current_version = meta["version"] if meta else None
            current_status = row.get("status") if row else None
            if row is None or meta is None:
                reasons.append("规则已删除或归档")
            else:
                if current_status == "已停用":
                    reasons.append("规则已停用，旧解释保留当时证据，重算需重新确认")
                if current_version != snap["version"]:
                    reasons.append(
                        f"规则已修订到 v{current_version}，旧解释仍引用 v{snap['version']} 的证据"
                    )
            notes.append({
                "ruleCode": snap["ruleCode"],
                "snapshotVersion": snap["version"],
                "currentVersion": current_version,
                "snapshotStatus": snap["status"],
                "currentStatus": current_status,
                "stale": bool(reasons),
                "reason": "；".join(reasons) if reasons else "规则条件未变化，证据仍有效",
                "jump": {"module": "filter", "ruleId": snap["ruleId"], "version": snap["version"]},
            })
        return notes


evidence = EvidenceStore()
