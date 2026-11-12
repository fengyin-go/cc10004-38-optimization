"""推导证据接口：样本编辑、筛选试算、标签重算、解释确认与解释板。

状态约定：
- ExpressionError（语法/字段问题）→ 400
- AmbiguityRequired（同名字段冲突待确认）→ 409，响应体给出候选身份
- 业务对象不存在 → 404
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.derive.bootstrap import reset_evidence
from app.services.derive.parser import ExpressionError
from app.services.derive.service import (
    AmbiguityRequired,
    filter_derive_service as fds,
    sample_service,
    tag_derive_service as tds,
)
from app.services.derive.store import evidence

router = APIRouter(prefix="/api/derive", tags=["推导证据"])

DEFAULT_OPERATOR = "值班管理员"


class SamplePatch(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class ConditionPayload(BaseModel):
    conditionText: str
    identityMap: dict[str, str] = Field(default_factory=dict)
    note: str | None = "业务修订"


class VersionPayload(BaseModel):
    expression: str
    identityMap: dict[str, str] = Field(default_factory=dict)
    note: str | None = "登记新版本"


class RecomputePayload(BaseModel):
    version: int | None = None
    objectId: str | None = None
    identityMap: dict[str, str] = Field(default_factory=dict)


class ConfirmPayload(BaseModel):
    runId: str
    objectId: str | None = None
    all: bool = False
    confirmedBy: str = DEFAULT_OPERATOR


def _handle_conflict(exc: AmbiguityRequired) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": "表达式存在同名字段冲突，请确认字段身份后再重算", "ambiguities": exc.ambiguities},
    )


# ---------------- 字段目录与样本 ----------------
@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return {"fields": sample_service.catalog()}


@router.get("/samples")
def list_samples() -> dict[str, Any]:
    return {"items": sample_service.list_objects()}


@router.patch("/samples/{object_id}")
def patch_sample(object_id: str, payload: SamplePatch) -> dict[str, Any]:
    try:
        row = sample_service.update_object(object_id, payload.values)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "item": row}


@router.post("/samples/reset")
def reset_samples() -> dict[str, Any]:
    from app.seed import SEED_ROWS

    items = sample_service.reset_objects(SEED_ROWS["sample_object"])
    return {"ok": True, "items": items}


@router.post("/reset")
def reset_all() -> dict[str, Any]:
    """把演示数据、运行记录和确认解释全部恢复到初始状态。"""
    reset_evidence()
    return {"ok": True}


# ---------------- 数据筛选：条件版本与试算 ----------------
@router.get("/filter/{rule_id}/condition")
def get_filter_condition(rule_id: int) -> dict[str, Any]:
    payload = evidence.filter_payload(rule_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"筛选规则 {rule_id} 还没有可执行条件")
    return payload


@router.put("/filter/{rule_id}/condition")
def put_filter_condition(rule_id: int, payload: ConditionPayload) -> dict[str, Any]:
    try:
        fds.prepare_condition(
            rule_id, payload.conditionText, payload.identityMap, note=payload.note or "业务修订"
        )
    except AmbiguityRequired as exc:
        raise _handle_conflict(exc) from exc
    except ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = evidence.filter_payload(rule_id)
    return {"ok": True, "condition": result}


@router.post("/filter/{rule_id}/trial")
def trial_filter(rule_id: int, object_id: str | None = None) -> dict[str, Any]:
    try:
        return fds.trial(rule_id, object_id)
    except AmbiguityRequired as exc:
        raise _handle_conflict(exc) from exc
    except ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/filter/{rule_id}/runs")
def filter_runs(rule_id: int) -> dict[str, Any]:
    return {"items": [
        {
            "runId": item["runId"], "ranAt": item["ranAt"], "version": item["version"],
            "expression": item.get("expression"),
            "coverageCount": sum(1 for r in item["results"] if r["hit"]),
            "totalCount": len(item["results"]),
        }
        for item in evidence.list_runs(scope="filter", owner_id=rule_id)
    ]}


@router.post("/filter/{rule_id}/confirm")
def confirm_filter(rule_id: int, payload: ConfirmPayload) -> dict[str, Any]:
    try:
        if payload.all:
            summary = fds.confirm_all(rule_id, payload.runId, payload.confirmedBy)
            return {"ok": True, **summary}
        if not payload.objectId:
            raise HTTPException(status_code=400, detail="确认单条解释时必须提供 objectId")
        expl, deduped = fds.confirm_trial(rule_id, payload.runId, payload.objectId, payload.confirmedBy)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True, "deduped": deduped,
        "message": "该解释已存在，重复确认只保留一份有效解释" if deduped else "解释已确认",
        "explanation": fds._decorate(expl),
    }


@router.get("/filter/{rule_id}/explanations")
def filter_explanations(rule_id: int, version: int | None = None) -> dict[str, Any]:
    return {"items": fds.explanations(rule_id, version)}


# ---------------- 数据标签：版本、重算与解释板 ----------------
@router.get("/tag/{tag_id}/board")
def tag_board(tag_id: int) -> dict[str, Any]:
    try:
        return tds.explanation_board(tag_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tag/{tag_id}/version")
def create_tag_version(tag_id: int, payload: VersionPayload) -> dict[str, Any]:
    try:
        item = tds.prepare_expression(
            tag_id, payload.expression, payload.identityMap, note=payload.note or "登记新版本"
        )
    except AmbiguityRequired as exc:
        raise _handle_conflict(exc) from exc
    except ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "version": item}


@router.post("/tag/{tag_id}/recompute")
def recompute_tag(tag_id: int, payload: RecomputePayload) -> dict[str, Any]:
    try:
        return tds.recompute(
            tag_id, version=payload.version, object_id=payload.objectId,
            identity_map=payload.identityMap,
        )
    except AmbiguityRequired as exc:
        raise _handle_conflict(exc) from exc
    except ExpressionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tag/{tag_id}/runs")
def tag_runs(tag_id: int) -> dict[str, Any]:
    return {"items": tds.runs(tag_id)}


@router.get("/tag/{tag_id}/runs/{run_id}")
def tag_run_detail(tag_id: int, run_id: str) -> dict[str, Any]:
    try:
        return tds.run_detail(tag_id, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tag/{tag_id}/confirm")
def confirm_tag(tag_id: int, payload: ConfirmPayload) -> dict[str, Any]:
    try:
        if payload.all:
            summary = tds.confirm_all(tag_id, payload.runId, payload.confirmedBy)
            return {"ok": True, **summary}
        if not payload.objectId:
            raise HTTPException(status_code=400, detail="确认单条解释时必须提供 objectId")
        expl, deduped = tds.confirm(tag_id, payload.runId, payload.objectId, payload.confirmedBy)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    decorated = dict(expl)
    decorated["staleNotes"] = evidence.staleness(expl.get("snapshots", []))
    return {
        "ok": True, "deduped": deduped,
        "message": "该解释已存在，重复确认只保留一份有效解释" if deduped else "解释已确认",
        "explanation": decorated,
    }
